"""ESPN public scoreboard — recent NFL final scores for ledger settlement."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from sharp_scout.data.espn_cfb import _BROWSER_HEADERS, _FINAL_STATUSES, _get_json
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

ESPN_SCOREBOARD = (
    "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)
ESPN_SCOREBOARD_FALLBACK = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)


def _team_code(team: dict[str, Any]) -> str:
    raw = team.get("abbreviation") or team.get("shortDisplayName") or team.get("displayName") or ""
    return normalize_team(str(raw), "nfl")


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

    season = week = None
    season_block = event.get("season") or {}
    if season_block.get("year") is not None:
        try:
            season = int(season_block["year"])
        except (TypeError, ValueError):
            season = None
    week_block = event.get("week")
    if week_block is not None:
        try:
            week = int(week_block.get("number") if isinstance(week_block, dict) else week_block)
        except (TypeError, ValueError):
            week = None

    return {
        "event_id": str(event.get("id") or comp.get("id") or ""),
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "season": season,
        "week": week,
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
        logger.warning("ESPN NFL scoreboard returned no events for %s", params)
        return []

    rows: list[dict[str, Any]] = []
    for event in events:
        parsed = _parse_event(event)
        if parsed:
            rows.append(parsed)
    return rows


def fetch_espn_nfl_scores(
    *,
    season: int | None = None,
    weeks: list[int] | None = None,
    lookback_days: int = 21,
) -> list[dict[str, Any]]:
    """Return final NFL scores from ESPN (deduped by away@home)."""
    season = season or datetime.now(timezone.utc).year
    by_key: dict[str, dict[str, Any]] = {}

    if weeks:
        for week in weeks:
            for row in _fetch_scoreboard(
                {"year": season, "seasontype": 2, "week": week, "limit": 200}
            ):
                by_key[f"{row['away_team']}@{row['home_team']}"] = row

    now = datetime.now(timezone.utc)
    for offset in range(lookback_days + 1):
        day = now - timedelta(days=offset)
        d = day.strftime("%Y%m%d")
        for row in _fetch_scoreboard({"dates": d, "limit": 200}):
            by_key[f"{row['away_team']}@{row['home_team']}"] = row

    logger.info("ESPN NFL: %d final scores loaded (season=%s)", len(by_key), season)
    return list(by_key.values())


ESPN_NFL_INJURIES = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
ESPN_NFL_TEAMS = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/teams"


def fetch_espn_nfl_injuries() -> list[dict[str, Any]]:
    """Live ESPN NFL injury report (Out / Doubtful / Questionable / IR)."""
    payload = _get_json(ESPN_NFL_INJURIES)
    if not isinstance(payload, dict):
        return []
    out: list[dict[str, Any]] = []
    for team_block in payload.get("injuries") or []:
        team_meta = team_block.get("team") or {}
        team = _team_code(team_meta) if team_meta else ""
        if not team and team_block.get("displayName"):
            team = normalize_team(str(team_block["displayName"]), "nfl")
        for item in team_block.get("injuries") or []:
            athlete = item.get("athlete") or {}
            name = athlete.get("displayName") or athlete.get("shortName") or ""
            status = item.get("status") or ""
            pos = (athlete.get("position") or {}).get("abbreviation") or ""
            if not name:
                continue
            out.append(
                {
                    "player": str(name).strip(),
                    "team": team,
                    "position": str(pos),
                    "status": str(status).strip(),
                    "detail": item.get("shortComment") or item.get("longComment") or "",
                }
            )
    logger.info("ESPN NFL injuries: %d rows", len(out))
    return out


def _espn_team_id_map() -> dict[str, str]:
    payload = _get_json(f"{ESPN_NFL_TEAMS}?limit=50")
    mapping: dict[str, str] = {}
    if not isinstance(payload, dict):
        return mapping
    for block in payload.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        ent = block.get("team") or {}
        abbr = ent.get("abbreviation") or ""
        tid = ent.get("id")
        if abbr and tid:
            mapping[normalize_team(str(abbr), "nfl")] = str(tid)
    return mapping


def fetch_espn_nfl_roster(team: str) -> list[dict[str, Any]]:
    """Current-season roster with position (ESPN)."""
    team = normalize_team(team, "nfl")
    ids = _espn_team_id_map()
    tid = ids.get(team)
    if not tid:
        return []
    payload = _get_json(
        f"https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/teams/{tid}/roster"
    )
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    rank: dict[str, int] = {}
    for group in payload.get("athletes") or []:
        pos = (group.get("position") or {}).get("abbreviation") or group.get("position") or ""
        pos = str(pos)
        for athlete in group.get("items") or []:
            name = athlete.get("displayName") or athlete.get("fullName") or ""
            if not name:
                continue
            rank[pos] = rank.get(pos, 0) + 1
            apos = (athlete.get("position") or {}).get("abbreviation") or pos
            rows.append(
                {
                    "player": str(name).strip(),
                    "team": team,
                    "position": str(apos),
                    "depth_rank": rank[pos],
                    "status": (athlete.get("status") or {}).get("name") or athlete.get("status") or "",
                }
            )
    return rows
