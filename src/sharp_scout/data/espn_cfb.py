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

# ESPN's `site.api.espn.com` host now 403s automated requests, which silently
# broke ledger settlement. The `site.web.api.espn.com` host serves the same
# scoreboard payload and still responds 200 with a browser User-Agent, so it is
# the primary; the old host is kept as a fallback.
ESPN_SCOREBOARD = (
    "https://site.web.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
)
ESPN_SCOREBOARD_FALLBACK = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
)
# ESPN 403s non-browser User-Agents (e.g. "SharpScout/1.0"), which silently
# breaks automatic settlement. Present as a real browser instead.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/college-football/scoreboard/",
    "Origin": "https://www.espn.com",
}
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


def _get_json(url: str) -> dict[str, Any] | None:
    """GET a URL as a browser and parse JSON, or None on any failure."""
    try:
        req = Request(url, headers=_BROWSER_HEADERS)
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _fetch_scoreboard(params: dict[str, Any]) -> list[dict[str, Any]]:
    qs = urlencode(params)
    payload = _get_json(f"{ESPN_SCOREBOARD}?{qs}")
    events = payload.get("events") if isinstance(payload, dict) else None
    if not events:
        payload = _get_json(f"{ESPN_SCOREBOARD_FALLBACK}?{qs}")
        events = payload.get("events") if isinstance(payload, dict) else None
    if not events:
        logger.warning("ESPN CFB scoreboard returned no events for %s", params)
        return []

    rows: list[dict[str, Any]] = []
    for event in events:
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
