"""Gate GitHub scheduled NBA shadow runs by triggering cron + intended ET slot."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Primary scans (weekdays 3:00 PM ET; weekends 11:00 AM ET)
WEEKDAY_PRIMARY = time(15, 0)
WEEKEND_PRIMARY = time(11, 0)
# Backup scans (weekdays 5:00 PM ET; weekends 1:00 PM ET)
WEEKDAY_BACKUP = time(17, 0)
WEEKEND_BACKUP = time(13, 0)

# Backward-compatible aliases (primary slots)
WEEKDAY_TARGET = WEEKDAY_PRIMARY
WEEKEND_TARGET = WEEKEND_PRIMARY

CRON_WEEKDAY_PRIMARY_EDT = "0 19 * * 1-5"  # 3:00 PM ET (EDT, UTC-4)
CRON_WEEKDAY_PRIMARY_EST = "0 20 * * 1-5"  # 3:00 PM ET (EST, UTC-5)
CRON_WEEKDAY_BACKUP_EDT = "0 21 * * 1-5"  # 5:00 PM ET (EDT)
CRON_WEEKDAY_BACKUP_EST = "0 22 * * 1-5"  # 5:00 PM ET (EST)

CRON_WEEKEND_PRIMARY_EDT = "0 15 * * 0,6"  # 11:00 AM ET (EDT)
CRON_WEEKEND_PRIMARY_EST = "0 16 * * 0,6"  # 11:00 AM ET (EST)
CRON_WEEKEND_BACKUP_EDT = "0 17 * * 0,6"  # 1:00 PM ET (EDT)
CRON_WEEKEND_BACKUP_EST = "0 18 * * 0,6"  # 1:00 PM ET (EST)

# Legacy names (tests / docs that referenced old 4:30 PM weekday crons)
CRON_WEEKDAY_EDT = CRON_WEEKDAY_PRIMARY_EDT
CRON_WEEKDAY_EST = CRON_WEEKDAY_PRIMARY_EST
CRON_WEEKEND_EDT = CRON_WEEKEND_PRIMARY_EDT
CRON_WEEKEND_EST = CRON_WEEKEND_PRIMARY_EST

PRIMARY_CRONS = frozenset(
    {
        CRON_WEEKDAY_PRIMARY_EDT,
        CRON_WEEKDAY_PRIMARY_EST,
        CRON_WEEKEND_PRIMARY_EDT,
        CRON_WEEKEND_PRIMARY_EST,
    }
)
BACKUP_CRONS = frozenset(
    {
        CRON_WEEKDAY_BACKUP_EDT,
        CRON_WEEKDAY_BACKUP_EST,
        CRON_WEEKEND_BACKUP_EDT,
        CRON_WEEKEND_BACKUP_EST,
    }
)
ALL_CRONS = PRIMARY_CRONS | BACKUP_CRONS

DEFAULT_MAX_LATE_HOURS = 4

NBA_SCAN_SCHEDULE_LABEL = (
    "weekdays 3:00 PM ET (5:00 PM backup) & weekends 11:00 AM ET (1:00 PM backup)"
)


def target_time_for_et_date(et_now: datetime) -> time:
    """Return the next primary local run time for the given ET calendar day."""
    wd = et_now.weekday()  # Mon=0 .. Sun=6
    if wd <= 4:
        return WEEKDAY_PRIMARY
    return WEEKEND_PRIMARY


def is_backup_cron(cron: str) -> bool:
    return cron.strip() in BACKUP_CRONS


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


def _slot_time_for_cron(cron: str) -> tuple[bool, time]:
    """Return (is_weekend_slot, intended ET time) for a known cron line."""
    cron = cron.strip()
    if cron in {
        CRON_WEEKEND_PRIMARY_EDT,
        CRON_WEEKEND_PRIMARY_EST,
        CRON_WEEKEND_BACKUP_EDT,
        CRON_WEEKEND_BACKUP_EST,
    }:
        backup = cron in BACKUP_CRONS
        return True, WEEKEND_BACKUP if backup else WEEKEND_PRIMARY
    backup = cron in BACKUP_CRONS
    return False, WEEKDAY_BACKUP if backup else WEEKDAY_PRIMARY


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


def expected_cron_for_intended_slot(intended: datetime, *, slot_time: time | None = None) -> str:
    """Cron line that matches ``intended`` (localized ET) for the configured slot."""
    if intended.tzinfo is None:
        intended = intended.replace(tzinfo=ET)
    else:
        intended = intended.astimezone(ET)
    slot_time = slot_time or target_time_for_et_date(intended)
    intended = datetime.combine(intended.date(), slot_time, tzinfo=ET)
    offset = intended.utcoffset() or timedelta(0)
    is_edt = offset == timedelta(hours=-4)
    is_weekend = intended.weekday() >= 5
    if is_weekend:
        if slot_time == WEEKEND_BACKUP:
            return CRON_WEEKEND_BACKUP_EDT if is_edt else CRON_WEEKEND_BACKUP_EST
        return CRON_WEEKEND_PRIMARY_EDT if is_edt else CRON_WEEKEND_PRIMARY_EST
    if slot_time == WEEKDAY_BACKUP:
        return CRON_WEEKDAY_BACKUP_EDT if is_edt else CRON_WEEKDAY_BACKUP_EST
    return CRON_WEEKDAY_PRIMARY_EDT if is_edt else CRON_WEEKDAY_PRIMARY_EST


def intended_et_date_from_cron(
    trigger_cron: str,
    now: datetime,
    *,
    max_late_hours: float = DEFAULT_MAX_LATE_HOURS,
) -> date | None:
    """ET calendar date for the slot this cron represents, when allowed."""
    trigger_cron = trigger_cron.strip()
    if trigger_cron not in ALL_CRONS:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    nominal = latest_nominal_fire_utc(
        trigger_cron, now, max_late=timedelta(hours=max_late_hours)
    )
    if nominal is None:
        return None
    return nominal.astimezone(ET).date()


def primary_scan_satisfied_for_et_date(et_day: date) -> bool:
    """True when a pre-tip score-model scan was recorded for this ET calendar day."""
    from sharp_scout.nba.score_model.paper import load_paper_store
    from sharp_scout.utils.kickoff import parse_kickoff_utc

    try:
        store = load_paper_store()
    except Exception:  # noqa: BLE001
        return False
    for g in store.get("games") or []:
        for s in g.get("scans") or []:
            if s.get("after_tip"):
                continue
            at = parse_kickoff_utc(s.get("at"))
            if at is None:
                continue
            if at.astimezone(ET).date() == et_day:
                return True
    return False


def scheduled_cron_run_allowed(
    trigger_cron: str,
    now: datetime,
    *,
    max_late_hours: float = DEFAULT_MAX_LATE_HOURS,
) -> bool:
    """True when ``trigger_cron`` is the correct seasonal line for the intended ET slot."""
    trigger_cron = trigger_cron.strip()
    if trigger_cron not in ALL_CRONS:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    max_late = timedelta(hours=max_late_hours)
    nominal = latest_nominal_fire_utc(trigger_cron, now, max_late=max_late)
    if nominal is None:
        return False

    is_weekend, target = _slot_time_for_cron(trigger_cron)
    slot_local = nominal.astimezone(ET)
    intended = datetime.combine(slot_local.date(), target, tzinfo=ET)

    wd = intended.weekday()
    if is_weekend:
        if wd < 5:
            return False
    elif wd > 4:
        return False

    return trigger_cron == expected_cron_for_intended_slot(intended, slot_time=target)


def next_nba_scan_et(now: datetime | None = None) -> datetime:
    """Next primary GitHub scheduled NBA shadow run (honors weekday vs weekend ET and DST)."""
    if now is None:
        now = datetime.now(ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc).astimezone(ET)
    else:
        now = now.astimezone(ET)

    for day_offset in range(0, 8):
        day = now.date() + timedelta(days=day_offset)
        noon = datetime.combine(day, time(12, 0), tzinfo=ET)
        target_t = target_time_for_et_date(noon)
        candidate = datetime.combine(day, target_t, tzinfo=ET)
        if candidate > now:
            return candidate
    fallback_day = now.date() + timedelta(days=1)
    return datetime.combine(fallback_day, WEEKDAY_PRIMARY, tzinfo=ET)
