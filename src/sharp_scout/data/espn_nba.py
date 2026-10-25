"""ESPN public scoreboard + box scores for NBA paper-ledger settlement."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from sharp_scout.data.espn_cfb import _BROWSER_HEADERS, _FINAL_STATUSES, _get_json
from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

ESPN_SCOREBOARD = (
    "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)
ESPN_SCOREBOARD_FALLBACK = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)
ESPN_SUMMARY = (
    "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
)

# ESPN scoreboard abbreviations that differ from Odds API / internal codes.
ESPN_NBA_ABBREV: dict[str, str] = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "SA": "SAS",
    "UTAH": "UTA",
    "WSH": "WAS",
}


def _team_code(team: dict[str, Any]) -> str:
    raw = team.get("abbreviation") or team.get("shortDisplayName") or team.get("displayName") or ""
    code = str(raw).upper()
    code = ESPN_NBA_ABBREV.get(code, code)
    return normalize_nba_team(code)


def _parse_event(event: dict[str, Any]) -> dict[str, Any] | None:
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    status = ((comp.get("status") or {}).get("type") or {}).get("name") or ""
    if status not in _FINAL_STATUSES:
        return None

    home_team = away_team = None
    home_score = away_score = None
    for side in comp.get("competitors") or []:
        team = side.get("team") or {}
        code = _team_code(team)
        try:
            score = int(side.get("score") or 0)
        except (TypeError, ValueError):
            return None
        if side.get("homeAway") == "home":
            home_team, home_score = code, score
        else:
            away_team, away_score = code, score

    if not home_team or not away_team or home_score is None or away_score is None:
        return None

    kickoff = comp.get("date") or event.get("date")
    return {
        "event_id": str(event.get("id") or comp.get("id") or ""),
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "kickoff": kickoff,
        "source": "espn",
    }


def _fetch_scoreboard(params: dict[str, Any]) -> list[dict[str, Any]]:
    qs = urlencode(params)
    payload = _get_json(f"{ESPN_SCOREBOARD}?{qs}")
    events = payload.get("events") if isinstance(payload, dict) else None
    if not events:
        payload = _get_json(f"{ESPN_SCOREBOARD_FALLBACK}?{qs}")
        events = payload.get("events") if isinstance(payload, dict) else None
    if not events:
        logger.warning("ESPN NBA scoreboard returned no events for %s", params)
        return []

    rows: list[dict[str, Any]] = []
    for event in events:
        parsed = _parse_event(event)
        if parsed:
            rows.append(parsed)
    return rows


def fetch_espn_nba_scores(*, lookback_days: int = 10) -> list[dict[str, Any]]:
    """Return final NBA scores from ESPN (deduped by away@home)."""
    by_key: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for offset in range(lookback_days + 1):
        day = now - timedelta(days=offset)
        d = day.strftime("%Y%m%d")
        try:
            day_rows = _fetch_scoreboard({"dates": d, "limit": 200})
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESPN NBA scoreboard failed for %s: %s", d, exc)
            continue
        for row in day_rows:
            by_key[f"{row['away_team']}@{row['home_team']}"] = row

    logger.info("ESPN NBA: %d final scores loaded", len(by_key))
    return list(by_key.values())


def _parse_made_from_shooting(raw: str) -> float | None:
    """Parse '4-9' style shooting lines to made count."""
    if not raw:
        return None
    m = re.match(r"^(\d+)", str(raw).strip())
    if not m:
        return None
    return float(m.group(1))


def _player_stat_map(summary: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Map normalized player name -> {stat_key: value}."""
    out: dict[str, dict[str, float]] = {}
    box = summary.get("boxscore") or {}
    for team_block in box.get("players") or []:
        for stat_group in team_block.get("statistics") or []:
            labels = [str(x).upper() for x in (stat_group.get("labels") or stat_group.get("names") or [])]
            for ath in stat_group.get("athletes") or []:
                athlete = ath.get("athlete") or {}
                name = str(athlete.get("displayName") or athlete.get("shortName") or "").strip()
                if not name:
                    continue
                stats = ath.get("stats") or []
                row: dict[str, float] = {}
                for i, label in enumerate(labels):
                    if i >= len(stats):
                        break
                    val = stats[i]
                    if label in ("PTS", "POINTS"):
                        try:
                            row["player_points"] = float(val)
                        except (TypeError, ValueError):
                            pass
                    elif label in ("REB", "REBS", "REBOUND"):
                        try:
                            row["player_rebounds"] = float(val)
                        except (TypeError, ValueError):
                            pass
                    elif label in ("AST", "ASSISTS"):
                        try:
                            row["player_assists"] = float(val)
                        except (TypeError, ValueError):
                            pass
                    elif label in ("3PT", "3-PT", "3PM"):
                        made = _parse_made_from_shooting(str(val))
                        if made is not None:
                            row["player_threes"] = made
                if row:
                    key = name.lower()
                    out[key] = {**out.get(key, {}), **row}
    return out


def fetch_espn_nba_box_scores(event_ids: list[str]) -> dict[str, dict[str, dict[str, float]]]:
    """event_id -> player_name_lower -> market stat values."""
    result: dict[str, dict[str, dict[str, float]]] = {}
    for eid in event_ids:
        if not eid:
            continue
        try:
            summary = _get_json(f"{ESPN_SUMMARY}?{urlencode({'event': eid})}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESPN NBA summary failed for %s: %s", eid, exc)
            continue
        if isinstance(summary, dict):
            try:
                result[str(eid)] = _player_stat_map(summary)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ESPN NBA box parse failed for %s: %s", eid, exc)
    return result
