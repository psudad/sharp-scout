"""Gate GitHub scheduled NBA shadow runs by triggering cron + intended ET slot."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

WEEKDAY_TARGET = time(16, 30)  # Mon–Fri 4:30 PM ET
WEEKEND_TARGET = time(11, 0)  # Sat–Sun 11:00 AM ET

CRON_WEEKDAY_EDT = "30 20 * * 1-5"
CRON_WEEKDAY_EST = "30 21 * * 1-5"
CRON_WEEKEND_EDT = "0 15 * * 0,6"
CRON_WEEKEND_EST = "0 16 * * 0,6"

ALL_CRONS = frozenset(
    {CRON_WEEKDAY_EDT, CRON_WEEKDAY_EST, CRON_WEEKEND_EDT, CRON_WEEKEND_EST}
)

DEFAULT_MAX_LATE_HOURS = 4


def target_time_for_et_date(et_now: datetime) -> time:
    """Return the configured local run time for the given ET calendar day."""
    wd = et_now.weekday()  # Mon=0 .. Sun=6
    if wd <= 4:
        return WEEKDAY_TARGET
    return WEEKEND_TARGET


def _github_utc_dow(dt: datetime) -> int:
    """GitHub cron DOW: 0=Sunday .. 6=Saturday."""
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


def _parse_cron_fields(cron: str) -> tuple[int, int, str]:
    parts = cron.split()
    if len(parts) != 5:
        raise ValueError(f"unsupported cron: {cron!r}")
    minute, hour, _dom, _month, dow = parts
    return int(minute), int(hour), dow


def latest_nominal_fire_utc(
    cron: str,
    now: datetime,
    *,
    max_late: timedelta,
) -> datetime | None:
    """Most recent UTC instant this cron fired at or before ``now``, within ``max_late``."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    minute, hour, dow = _parse_cron_fields(cron)
    best: datetime | None = None
    # Late fires can cross one UTC day; scan a small window of prior calendar days.
    for days_back in range(0, 3):
        day = now.date() - timedelta(days=days_back)
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)
        if candidate > now:
            continue
        if not _utc_dow_matches(candidate, dow):
            continue
        lag = now - candidate
        if lag > max_late:
            continue
        if best is None or candidate > best:
            best = candidate
    return best


def expected_cron_for_intended_slot(intended: datetime) -> str:
    """Cron line that matches ``intended`` (localized ET) for the configured slot."""
    if intended.tzinfo is None:
        intended = intended.replace(tzinfo=ET)
    else:
        intended = intended.astimezone(ET)
    offset = intended.utcoffset() or timedelta(0)
    is_edt = offset == timedelta(hours=-4)
    is_weekend = intended.weekday() >= 5
    if is_weekend:
        return CRON_WEEKEND_EDT if is_edt else CRON_WEEKEND_EST
    return CRON_WEEKDAY_EDT if is_edt else CRON_WEEKDAY_EST


def _is_weekend_cron(cron: str) -> bool:
    return cron in {CRON_WEEKEND_EDT, CRON_WEEKEND_EST}


def scheduled_cron_run_allowed(
    trigger_cron: str,
    now: datetime,
    *,
    max_late_hours: float = DEFAULT_MAX_LATE_HOURS,
) -> bool:
    """True when ``trigger_cron`` is the correct seasonal line for the intended ET slot.

    Uses the nominal UTC fire time (from the cron schedule), not the delayed start
    clock, to pick the intended slot's calendar date and EDT/EST offset.
    """
    trigger_cron = trigger_cron.strip()
    if trigger_cron not in ALL_CRONS:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    max_late = timedelta(hours=max_late_hours)
    nominal = latest_nominal_fire_utc(trigger_cron, now, max_late=max_late)
    if nominal is None:
        return False

    is_weekend = _is_weekend_cron(trigger_cron)
    target = WEEKEND_TARGET if is_weekend else WEEKDAY_TARGET

    # Intended local slot date comes from the on-time mapping of this nominal UTC fire.
    slot_local = nominal.astimezone(ET)
    intended = datetime.combine(slot_local.date(), target, tzinfo=ET)

    wd = intended.weekday()
    if is_weekend:
        if wd < 5:
            return False
    elif wd > 4:
        return False

    return trigger_cron == expected_cron_for_intended_slot(intended)
