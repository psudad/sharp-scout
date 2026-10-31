"""Rest / travel schedule inputs for live score-model projections (ET game dates)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sharp_scout.nba.score_model.teams_geo import travel_miles
from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.utils.kickoff import parse_kickoff_utc


def _parse_last_played(blob: dict[str, str]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for team, raw in blob.items():
        dt = parse_kickoff_utc(raw)
        if dt is not None:
            out[str(team)] = dt
    return out


def rest_days_et(team: str, kickoff: Any, last_played: dict[str, datetime]) -> int | None:
    """Calendar rest using US/Eastern game dates (not UTC midnight)."""
    kick = parse_kickoff_utc(kickoff)
    if kick is None:
        return None
    prev = last_played.get(team)
    if prev is None:
        return None
    day_k = kickoff_date_et(kick)
    day_p = kickoff_date_et(prev)
    if day_k is None or day_p is None:
        return None
    return max((day_k - day_p).days, 0)


def three_in_four(team: str, kickoff: Any, recent_dates_et: dict[str, list[str]]) -> bool:
    kick = parse_kickoff_utc(kickoff)
    if kick is None:
        return False
    day_k = kickoff_date_et(kick)
    if day_k is None:
        return False
    window_start = day_k - timedelta(days=4)
    count = 0
    for raw in recent_dates_et.get(team) or []:
        try:
            d = datetime.fromisoformat(str(raw)).date()
        except ValueError:
            continue
        if window_start < d < day_k:
            count += 1
    return count >= 2


def schedule_projection_kwargs(
    engine: Any,
    *,
    home: str,
    away: str,
    kickoff: Any,
) -> dict[str, Any]:
    """Keyword args for V2Engine.project (stage 3+ schedule layer)."""
    last = _parse_last_played(getattr(engine, "team_last_played", {}) or {})
    last_site = dict(getattr(engine, "team_last_venue", {}) or {})
    recent = dict(getattr(engine, "team_recent_dates_et", {}) or {})
    hr = rest_days_et(home, kickoff, last)
    ar = rest_days_et(away, kickoff, last)
    return {
        "home_rest": hr,
        "away_rest": ar,
        "home_3in4": three_in_four(home, kickoff, recent),
        "away_3in4": three_in_four(away, kickoff, recent),
        "home_travel_mi": travel_miles(last_site.get(home, home), home)
        if last_site.get(home, home) != home
        else 0.0,
        "away_travel_mi": travel_miles(last_site.get(away, away), home)
        if last_site.get(away, away) != home
        else 0.0,
    }
