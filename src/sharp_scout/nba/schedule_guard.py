"""Gate GitHub scheduled NBA shadow runs to America/New_York weekday/weekend slots."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

WEEKDAY_TARGET = time(16, 30)  # Mon–Fri 4:30 PM ET
WEEKEND_TARGET = time(11, 0)  # Sat–Sun 11:00 AM ET
DEFAULT_TOLERANCE_MINUTES = 45


def target_time_for_et_date(et_now: datetime) -> time:
    """Return the configured local run time for the given ET calendar day."""
    wd = et_now.weekday()  # Mon=0 .. Sun=6
    if wd <= 4:
        return WEEKDAY_TARGET
    return WEEKEND_TARGET


def scheduled_slot_matches(
    now: datetime,
    *,
    tolerance_minutes: int = DEFAULT_TOLERANCE_MINUTES,
) -> bool:
    """True when ``now`` (any tz) falls within tolerance of the ET slot for that day."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    et = now.astimezone(ET)
    target = target_time_for_et_date(et)
    slot = datetime.combine(et.date(), target, tzinfo=ET)
    tol = timedelta(minutes=tolerance_minutes)
    return abs(et - slot) <= tol
