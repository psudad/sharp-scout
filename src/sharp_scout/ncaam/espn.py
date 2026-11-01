"""ESPN men's college basketball scoreboard (slate + finals)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from sharp_scout.ncaam.teams import normalize_ncaam

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
SCOREBOARD = (
    "https://site.web.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
)
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; SharpScout/1.0; +https://github.com/psudad/sharp-scout)",
    "Referer": "https://www.espn.com/mens-college-basketball/scoreboard/",
}


def _parse_event(ev: dict[str, Any]) -> dict[str, Any] | None:
    comp = (ev.get("competitions") or [{}])[0]
    home = away = None
    home_loc = away_loc = None
    for t in comp.get("competitors") or []:
        if not isinstance(t, dict):
            continue
        tm = t.get("team") or {}
        loc = str(tm.get("location") or tm.get("displayName") or "").strip()
        row = {
            "espn_id": str(ev.get("id") or ""),
            "display": tm.get("displayName"),
            "location": loc,
            "abbrev": tm.get("abbreviation"),
            "score": t.get("score"),
            "team_id": str(tm.get("id") or ""),
            "conference_id": str(tm.get("conferenceId") or ""),
        }
        if t.get("homeAway") == "home":
            home, home_loc = row, loc
        else:
            away, away_loc = row, loc
    if not home or not away:
        return None
    status = (comp.get("status") or {}).get("type") or {}
    tip_raw = comp.get("date") or ev.get("date")
    tip = None
    if isinstance(tip_raw, str):
        tip = datetime.fromisoformat(tip_raw.replace("Z", "+00:00"))
    neutral = bool(comp.get("neutralSite"))
    return {
        "espn_id": str(ev.get("id") or ""),
        "home_location": home_loc,
        "away_location": away_loc,
        "home_team": normalize_ncaam(home_loc) or home_loc,
        "away_team": normalize_ncaam(away_loc) or away_loc,
        "home_display": home.get("display"),
        "away_display": away.get("display"),
        "commence_time": tip,
        "neutral_site": neutral,
        "status_state": status.get("state"),
        "status_completed": status.get("completed"),
        "home_score": int(home["score"]) if str(home.get("score") or "").isdigit() else None,
        "away_score": int(away["score"]) if str(away.get("score") or "").isdigit() else None,
        "season_type": (ev.get("season") or {}).get("type"),
        "status_name": status.get("name"),
        "conference_game": bool(comp.get("conferenceCompetition")),
        "home_espn_team_id": home.get("team_id") or "",
        "away_espn_team_id": away.get("team_id") or "",
        "home_conference_id": home.get("conference_id") or "",
        "away_conference_id": away.get("conference_id") or "",
    }


def fetch_scoreboard(*, dates: str | None = None, limit: int = 400) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"groups": 50, "limit": limit}
    if dates:
        params["dates"] = dates
    with httpx.Client(timeout=45.0, headers=UA) as client:
        resp = client.get(SCOREBOARD, params=params)
        resp.raise_for_status()
        payload = resp.json()
    out: list[dict[str, Any]] = []
    for ev in payload.get("events") or []:
        if not isinstance(ev, dict):
            continue
        row = _parse_event(ev)
        if row:
            out.append(row)
    return out


def fetch_scoreboard_et_day(day: date) -> list[dict[str, Any]]:
    return fetch_scoreboard(dates=day.strftime("%Y%m%d"))


def fetch_final_scores(*, start: date, end: date | None = None) -> list[dict[str, Any]]:
    end = end or start
    scores: list[dict[str, Any]] = []
    d = start
    while d <= end:
        for row in fetch_scoreboard(dates=d.strftime("%Y%m%d")):
            if not row.get("status_completed"):
                continue
            hs, aw = row.get("home_score"), row.get("away_score")
            if hs is None or aw is None:
                continue
            scores.append(
                {
                    "event_id": row["espn_id"],
                    "espn_id": row["espn_id"],
                    "home_team": row["home_team"],
                    "away_team": row["away_team"],
                    "home_score": hs,
                    "away_score": aw,
                    "kickoff": row.get("commence_time"),
                }
            )
        d += timedelta(days=1)
    return scores


def et_dates_for_runner(now: datetime | None = None) -> list[date]:
    now = now or datetime.now(timezone.utc)
    et_now = now.astimezone(ET)
    days = [et_now.date()]
    if et_now.hour < 3:
        days.insert(0, et_now.date() - timedelta(days=1))
    return days
