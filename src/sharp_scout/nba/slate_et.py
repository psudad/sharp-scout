"""NBA slate windows in US Eastern (game dates, not UTC calendar)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sharp_scout.utils.kickoff import kickoff_in_horizon, parse_kickoff_utc
from sharp_scout.utils.slate import ET


def kickoff_date_et(kickoff: Any) -> date | None:
    kick = parse_kickoff_utc(kickoff)
    if kick is None:
        return None
    return kick.astimezone(ET).date()


def espn_events_for_injury_window(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    horizon_hours: float = 36.0,
) -> list[dict[str, Any]]:
    """All games on today's ET date plus tomorrow ET if within horizon_hours."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ET).date()
    tomorrow = today + timedelta(days=1)
    out: list[dict[str, Any]] = []
    for ev in events:
        kick = parse_kickoff_utc(ev.get("kickoff"))
        if kick is None:
            continue
        if kick < now - timedelta(minutes=15):
            continue
        day = kick.astimezone(ET).date()
        if day == today:
            out.append(ev)
        elif day == tomorrow and kickoff_in_horizon(kick, horizon_hours, now=now):
            out.append(ev)
    out.sort(key=lambda e: parse_kickoff_utc(e.get("kickoff")) or now)
    return out
