"""ESPN public scoreboard — live NCAAF final scores for ledger settlement."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
)
_FINAL_STATUSES = frozenset({"STATUS_FINAL", "STATUS_FINAL_OVERTIME"})


def _team_code(team: dict[str, Any]) -> str:
    raw = team.get("abbreviation") or team.get("shortDisplayName") or team.get("displayName") or ""
    return normalize_team(str(raw), "ncaaf")


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
    if event.get("week") is not None and event.get("week") == event.get("week"):
        try:
            week = int(event["week"].get("number") if isinstance(event["week"], dict) else event["week"])
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
    url = f"{ESPN_SCOREBOARD}?{urlencode(params)}"
    try:
        req = Request(url, headers={"User-Agent": "SharpScout/1.0"})
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ESPN CFB scoreboard failed %s: %s", params, exc)
        return []

    rows: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        parsed = _parse_event(event)
        if parsed:
            rows.append(parsed)
    return rows


def fetch_espn_cfb_scores(
    *,
    season: int | None = None,
    weeks: list[int] | None = None,
    dates: list[str] | None = None,
    lookback_days: int = 14,
) -> list[dict[str, Any]]:
    """Return final FBS/FCS scores from ESPN (deduped by away@home)."""
    season = season or datetime.now(timezone.utc).year
    by_key: dict[str, dict[str, Any]] = {}

    if dates:
        for d in dates:
            for row in _fetch_scoreboard({"dates": d, "limit": 400}):
                by_key[f"{row['away_team']}@{row['home_team']}"] = row
    else:
        week_list = weeks if weeks is not None else list(range(1, 4))
        for week in week_list:
            for row in _fetch_scoreboard(
                {"year": season, "seasontype": 2, "week": week, "limit": 400}
            ):
                by_key[f"{row['away_team']}@{row['home_team']}"] = row

        # Opening week / neutral-site games sometimes sit on calendar dates outside week buckets.
        now = datetime.now(timezone.utc)
        for offset in range(lookback_days + 1):
            day = now - timedelta(days=offset)
            d = day.strftime("%Y%m%d")
            for row in _fetch_scoreboard({"dates": d, "limit": 400}):
                by_key[f"{row['away_team']}@{row['home_team']}"] = row

    logger.info("ESPN CFB: %d final scores loaded (season=%s)", len(by_key), season)
    return list(by_key.values())
