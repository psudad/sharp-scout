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
