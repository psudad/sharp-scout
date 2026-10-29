"""Scheduled Odds API credit pause until billing reset (America/New_York dates)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Scheduled heavy workflows resume on this ET calendar date (inclusive).
ODDS_CREDIT_RESUME_ET_DATE = date(2026, 11, 6)

# One-off NFL Sunday scan during the pause (Nov 1 2026, EST — DST ends earlier that day).
NOV1_2026_ET_DATE = date(2026, 11, 1)
NOV1_NFL_PREGAME_CRON = "0 14 * * 0"  # 09:00 ET when EST (UTC-5); tolerate late GitHub starts
NOV1_NOMINAL_ET = time(9, 0)
DEFAULT_MAX_LATE_HOURS = 4.0


def et_calendar_date(when: datetime | None = None) -> date:
    if when is None:
        when = datetime.now(timezone.utc)
    elif when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(ET).date()


def scheduled_odds_pause_active(when: datetime | None = None) -> bool:
    """True while ET date is strictly before the Nov 6, 2026 billing reset."""
    return et_calendar_date(when) < ODDS_CREDIT_RESUME_ET_DATE


def _github_utc_dow(dt: datetime) -> int:
    return (dt.weekday() + 1) % 7


def _utc_dow_matches(dt: datetime, dow_field: str) -> bool:
    if dow_field == "*":
        return True
    allowed: set[int] = set()
    for part in dow_field.split(","):
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            allowed.update(range(int(start_s), int(end_s) + 1))
        else:
            allowed.add(int(part))
    return _github_utc_dow(dt) in allowed


def latest_nominal_cron_fire_utc(
    cron: str,
    now: datetime,
    *,
    max_late: timedelta,
) -> datetime | None:
    parts = cron.split()
    if len(parts) != 5:
        return None
    minute, hour, _dom, _month, dow = parts
    minute_i, hour_i = int(minute), int(hour)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    best: datetime | None = None
    for days_back in range(0, 3):
        day = now.date() - timedelta(days=days_back)
        candidate = datetime(day.year, day.month, day.day, hour_i, minute_i, tzinfo=timezone.utc)
        if candidate > now:
            continue
        if not _utc_dow_matches(candidate, dow):
            continue
        if now - candidate > max_late:
            continue
        if best is None or candidate > best:
            best = candidate
    return best


def nov1_2026_nfl_sunday_pregame_allowed(
    trigger_cron: str,
    now: datetime,
    *,
    max_late_hours: float = DEFAULT_MAX_LATE_HOURS,
) -> bool:
    """Allow exactly one scheduled pregame during the pause: Nov 1 2026 NFL sides only."""
    trigger_cron = trigger_cron.strip()
    if trigger_cron != NOV1_NFL_PREGAME_CRON:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    max_late = timedelta(hours=max_late_hours)
    nominal = latest_nominal_cron_fire_utc(trigger_cron, now, max_late=max_late)
    if nominal is None:
        return False
    # Intended slot date follows the nominal 9:00 AM ET mapping (not delayed job start).
    slot_local = nominal.astimezone(ET)
    intended = datetime.combine(slot_local.date(), NOV1_NOMINAL_ET, tzinfo=ET)
    if intended.date() != NOV1_2026_ET_DATE:
        return False
    if intended.weekday() != 6:  # Sunday
        return False
    return True


def pregame_scheduled_allowed(
    trigger_cron: str,
    now: datetime,
    *,
    max_late_hours: float = DEFAULT_MAX_LATE_HOURS,
) -> tuple[bool, bool]:
    """Return (proceed, nov1_nfl_sides_only)."""
    if not scheduled_odds_pause_active(now):
        return True, False
    if nov1_2026_nfl_sunday_pregame_allowed(trigger_cron, now, max_late_hours=max_late_hours):
        return True, True
    return False, False


def workflow_scheduled_allowed_during_pause(workflow: str) -> bool:
    """Props / NCAAF lines have no pause exceptions."""
    _ = workflow
    return False
