"""Slate windows — college football week (Tue–Mon ET) and kickoff filters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_commence(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _as_utc(raw)
    if isinstance(raw, str) and raw:
        try:
            return _as_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def college_week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return UTC bounds for the college football week containing ``now``.

    Week = Tuesday 00:00 America/New_York through the following Monday 23:59:59 ET.
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    local = now.astimezone(ET)
    # Tuesday = weekday 1
    days_since_tuesday = (local.weekday() - 1) % 7
    week_start_local = (local - timedelta(days=days_since_tuesday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)
    return week_start_local.astimezone(timezone.utc), week_end_local.astimezone(timezone.utc)


def filter_events_college_week(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    include_started: bool = False,
) -> list[dict[str, Any]]:
    """Keep events whose kickoff falls in the current college week (ET Tue–Mon)."""
    start, end = college_week_bounds(now)
    now = _as_utc(now or datetime.now(timezone.utc))
    out: list[dict[str, Any]] = []
    for ev in events:
        kickoff = parse_commence(ev.get("commence_time"))
        if kickoff is None:
            continue
        if kickoff < start or kickoff > end:
            continue
        if not include_started and kickoff < now - timedelta(minutes=15):
            continue
        out.append(ev)
    return out


def filter_plays_college_week(
    plays: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Keep ledger plays whose kickoff falls in the current college week."""
    start, end = college_week_bounds(now)
    out: list[dict[str, Any]] = []
    for play in plays:
        kickoff = parse_commence(play.get("kickoff") or play.get("commence_time"))
        if kickoff is None:
            continue
        if start <= kickoff <= end:
            out.append(play)
    return out
