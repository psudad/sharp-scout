"""NBA slate windows in US Eastern (game dates, not UTC calendar)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sharp_scout.copy.explain import kickoff_sort_key
from sharp_scout.utils.kickoff import kickoff_in_horizon, parse_kickoff_utc
from sharp_scout.utils.slate import ET


def kickoff_date_et(kickoff: Any) -> date | None:
    kick = parse_kickoff_utc(kickoff)
    if kick is None:
        return None
    return kick.astimezone(ET).date()


def _format_et_calendar_day(day: date) -> str:
    return f"{day.strftime('%a %b')} {day.day}"


def format_et_slate_day_label(day: date, *, reference: date | None = None) -> str:
    """Human group heading: Tonight, Tue Oct 27 / Tomorrow, Wed Oct 28 / Thu Oct 30."""
    reference = reference or datetime.now(ET).date()
    date_part = _format_et_calendar_day(day)
    delta = (day - reference).days
    if delta == 0:
        return f"Tonight, {date_part}"
    if delta == 1:
        return f"Tomorrow, {date_part}"
    return date_part


def format_kickoff_day_time_et(kickoff: Any) -> str:
    """Card line: Tue Oct 27 · 7:10 PM ET (always Eastern game date + tip)."""
    kick = parse_kickoff_utc(kickoff)
    if kick is None:
        return "Time TBD"
    local = kick.astimezone(ET)
    time_part = local.strftime("%-I:%M %p ET")
    return f"{_format_et_calendar_day(local.date())} · {time_part}"


def group_items_by_kickoff_et_date(
    items: list[dict[str, Any]],
    *,
    kickoff_key: str = "kickoff",
    reference: date | None = None,
) -> list[tuple[date, str, list[dict[str, Any]]]]:
    """Bucket rows by ET game date; groups ascending, items by tip-off within each day."""
    reference = reference or datetime.now(ET).date()
    buckets: dict[date, list[dict[str, Any]]] = {}
    for item in items:
        day = kickoff_date_et(item.get(kickoff_key))
        if day is None:
            continue
        buckets.setdefault(day, []).append(item)
    out: list[tuple[date, str, list[dict[str, Any]]]] = []
    for day in sorted(buckets):
        group = sorted(buckets[day], key=lambda row: kickoff_sort_key(row.get(kickoff_key)))
        out.append((day, format_et_slate_day_label(day, reference=reference), group))
    return out


def upcoming_slate_items(
    items: list[dict[str, Any]],
    *,
    kickoff_key: str = "kickoff",
    now: datetime | None = None,
    started_grace_minutes: int = 15,
) -> list[dict[str, Any]]:
    """Open/upcoming games on today's or future ET dates (exclude prior ET slates)."""
    now = now or datetime.now(timezone.utc)
    today_et = now.astimezone(ET).date()
    cutoff = now - timedelta(minutes=started_grace_minutes)
    out: list[dict[str, Any]] = []
    for item in items:
        raw = item.get(kickoff_key)
        kick = parse_kickoff_utc(raw)
        if kick is None or kick < cutoff:
            continue
        day = kickoff_date_et(raw)
        if day is not None and day < today_et:
            continue
        out.append(item)
    return out


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
