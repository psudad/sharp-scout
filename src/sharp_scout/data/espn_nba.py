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
    """Return final NBA scores from ESPN (deduped by away@home — settlement shortcut)."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=lookback_days)
    rows = fetch_espn_nba_finals_by_event(since=since, until=now)
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_key[f"{row['away_team']}@{row['home_team']}"] = row
    logger.info("ESPN NBA: %d final scores loaded (matchup dedupe)", len(by_key))
    return list(by_key.values())


def fetch_espn_nba_finals_by_event(
    *,
    since: datetime,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Final games keyed by ESPN event id (keeps repeat matchups)."""
    until = until or datetime.now(timezone.utc)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    by_eid: dict[str, dict[str, Any]] = {}
    day = since.date()
    end = until.date()
    while day <= end:
        d = day.strftime("%Y%m%d")
        try:
            day_rows = _fetch_scoreboard({"dates": d, "limit": 200})
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESPN NBA scoreboard failed for %s: %s", d, exc)
            day += timedelta(days=1)
            continue
        for row in day_rows:
            eid = str(row.get("event_id") or "")
            if eid:
                by_eid[eid] = row
            else:
                kick = row.get("kickoff") or d
                by_eid[f"{row['away_team']}@{row['home_team']}@{kick}"] = row
        day += timedelta(days=1)

    logger.info("ESPN NBA: %d finals by event (%s .. %s)", len(by_eid), since.date(), end)
    return sorted(by_eid.values(), key=lambda r: r.get("kickoff") or "")


def _parse_made_attempted(raw: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d+)\s*-\s*(\d+)", str(raw).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _stat_value(stats: list[dict[str, Any]], *names: str) -> str | None:
    for st in stats:
        nm = str(st.get("name") or st.get("label") or "").lower()
        for want in names:
            if want.lower() in nm:
                return st.get("displayValue") or st.get("value")
    return None


def parse_team_box_possessions(team_block: dict[str, Any]) -> float | None:
    """FGA - OREB + TOV + 0.44*FTA (team possessions estimate)."""
    stats = team_block.get("statistics") or []
    fga = oreb = tov = fta = 0
    fgm_pair = _parse_made_attempted(_stat_value(stats, "fieldGoalsMade-fieldGoalsAttempted") or "")
    if fgm_pair:
        _, fga = fgm_pair
    oreb_raw = _stat_value(stats, "offensiveRebounds")
    if oreb_raw is not None:
        oreb = int(float(oreb_raw))
    tov_raw = _stat_value(stats, "totalTurnovers", "turnovers")
    if tov_raw is not None:
        tov = int(float(tov_raw))
    ft_pair = _parse_made_attempted(_stat_value(stats, "freeThrowsMade-freeThrowsAttempted") or "")
    if ft_pair:
        _, fta = ft_pair
    if fga <= 0:
        return None
    return max(float(fga - oreb + tov + 0.44 * fta), 1.0)


def fetch_game_possessions(event_id: str) -> float | None:
    """Average team possessions from ESPN box score (non-fatal)."""
    if not event_id:
        return None
    try:
        summary = _get_json(f"{ESPN_SUMMARY}?{urlencode({'event': event_id})}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("ESPN poss fetch fail %s: %s", event_id, exc)
        return None
    if not isinstance(summary, dict):
        return None
    box = summary.get("boxscore") or {}
    teams = box.get("teams") or []
    poss: list[float] = []
    for tb in teams:
        try:
            p = parse_team_box_possessions(tb)
            if p:
                poss.append(p)
        except Exception:  # noqa: BLE001
            continue
    if not poss:
        return None
    return sum(poss) / len(poss)


def _parse_scheduled_event(event: dict[str, Any]) -> dict[str, Any] | None:
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    status = ((comp.get("status") or {}).get("type") or {}).get("name") or ""
    if status in _FINAL_STATUSES:
        return None
    home_team = away_team = None
    for side in comp.get("competitors") or []:
        team = side.get("team") or {}
        code = _team_code(team)
        if side.get("homeAway") == "home":
            home_team = code
        else:
            away_team = code
    if not home_team or not away_team:
        return None
    kickoff = comp.get("date") or event.get("date")
    return {
        "event_id": str(event.get("id") or comp.get("id") or ""),
        "home_team": home_team,
        "away_team": away_team,
        "kickoff": kickoff,
        "status": status,
    }


def fetch_espn_nba_upcoming(*, days_ahead: int = 2) -> list[dict[str, Any]]:
    """Scheduled (non-final) games on ESPN scoreboard for the next N calendar days."""
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for offset in range(days_ahead + 1):
        day = (now + timedelta(days=offset)).strftime("%Y%m%d")
        try:
            payload = _get_json(f"{ESPN_SCOREBOARD}?{urlencode({'dates': day, 'limit': 200})}")
            events = payload.get("events") if isinstance(payload, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESPN upcoming scoreboard failed for %s: %s", day, exc)
            continue
        if not events:
            continue
        for event in events:
            row = _parse_scheduled_event(event)
            if row:
                out.append(row)
    return out


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


ESPN_NBA_INJURIES = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
)


def fetch_espn_nba_injuries() -> list[dict[str, Any]]:
    """Free ESPN injury report: player, team code, status text."""
    try:
        payload = _get_json(ESPN_NBA_INJURIES)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ESPN NBA injuries fetch failed: %s", exc)
        return []
    if not isinstance(payload, dict):
        return []
    out: list[dict[str, Any]] = []
    for team_block in payload.get("injuries") or []:
        team_info = team_block.get("team") or {}
        team_raw = team_info.get("abbreviation") or team_info.get("displayName") or ""
        team = ESPN_NBA_ABBREV.get(str(team_raw).upper(), str(team_raw).upper())
        team = normalize_nba_team(team)
        for item in team_block.get("injuries") or []:
            athlete = item.get("athlete") or {}
            name = athlete.get("displayName") or athlete.get("shortName") or ""
            status = item.get("status") or item.get("type") or item.get("details", {}).get("type")
            if isinstance(status, dict):
                status = status.get("description") or status.get("name")
            if not name:
                continue
            out.append(
                {
                    "player": str(name).strip(),
                    "team": team,
                    "status": str(status or "").strip(),
                    "detail": item.get("shortComment") or item.get("longComment") or "",
                }
            )
    logger.info("ESPN NBA injuries: %d rows", len(out))
    return out
