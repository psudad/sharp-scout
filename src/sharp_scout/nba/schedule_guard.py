"""Gate GitHub scheduled NBA shadow runs by triggering cron + intended ET slot."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Primary scans (weekdays 1:07 PM ET; weekends 9:07 AM ET)
WEEKDAY_PRIMARY = time(13, 7)
WEEKEND_PRIMARY = time(9, 7)
# Backup scans (weekdays 4:07 PM ET; weekends 11:07 AM ET)
WEEKDAY_BACKUP = time(16, 7)
WEEKEND_BACKUP = time(11, 7)

# Backward-compatible aliases (primary slots)
WEEKDAY_TARGET = WEEKDAY_PRIMARY
WEEKEND_TARGET = WEEKEND_PRIMARY

# Off the top of the hour (:07) — GitHub delays/drops :00 schedules the most.
CRON_WEEKDAY_PRIMARY_EDT = "7 17 * * 1-5"  # 1:07 PM ET (EDT, UTC-4)
CRON_WEEKDAY_PRIMARY_EST = "7 18 * * 1-5"  # 1:07 PM ET (EST, UTC-5)
CRON_WEEKDAY_BACKUP_EDT = "7 20 * * 1-5"  # 4:07 PM ET (EDT)
CRON_WEEKDAY_BACKUP_EST = "7 21 * * 1-5"  # 4:07 PM ET (EST)

CRON_WEEKEND_PRIMARY_EDT = "7 13 * * 0,6"  # 9:07 AM ET (EDT)
CRON_WEEKEND_PRIMARY_EST = "7 14 * * 0,6"  # 9:07 AM ET (EST)
CRON_WEEKEND_BACKUP_EDT = "7 15 * * 0,6"  # 11:07 AM ET (EDT)
CRON_WEEKEND_BACKUP_EST = "7 16 * * 0,6"  # 11:07 AM ET (EST)

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

# Fallback lateness limit when the first tip-off of the day is unknown (ESPN unreachable).
DEFAULT_MAX_LATE_HOURS = 4
# When the first tip is known, a late GitHub start is allowed until this long before it
# (scans must land pre-tip). Lookback cap keeps a cron from matching a previous day's slot.
TIP_OFF_BUFFER = timedelta(minutes=10)
TIP_GATE_MAX_LOOKBACK_HOURS = 12

NBA_SCAN_SCHEDULE_LABEL = (
    "weekdays 1:07 PM ET (4:07 PM backup) & weekends 9:07 AM ET (11:07 AM backup)"
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


def _lookback(max_late_hours: float, first_tip_utc: datetime | None) -> timedelta:
    if first_tip_utc is not None:
        return timedelta(hours=max(max_late_hours, TIP_GATE_MAX_LOOKBACK_HOURS))
    return timedelta(hours=max_late_hours)


def intended_et_date_from_cron(
    trigger_cron: str,
    now: datetime,
    *,
    max_late_hours: float = DEFAULT_MAX_LATE_HOURS,
    first_tip_utc: datetime | None = None,
) -> date | None:
    """ET calendar date for the slot this cron represents, when allowed."""
    trigger_cron = trigger_cron.strip()
    if trigger_cron not in ALL_CRONS:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    nominal = latest_nominal_fire_utc(
        trigger_cron, now, max_late=_lookback(max_late_hours, first_tip_utc)
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
    first_tip_utc: datetime | None = None,
) -> bool:
    """True when ``trigger_cron`` is the correct seasonal line for the intended ET slot.

    Lateness: when ``first_tip_utc`` (first NBA tip-off of the ET day) is known, a delayed
    GitHub start is allowed until ``TIP_OFF_BUFFER`` before that tip, on the same ET day.
    When it is unknown, the fixed ``max_late_hours`` limit applies.
    """
    trigger_cron = trigger_cron.strip()
    if trigger_cron not in ALL_CRONS:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if first_tip_utc is not None and first_tip_utc.tzinfo is None:
        first_tip_utc = first_tip_utc.replace(tzinfo=timezone.utc)

    nominal = latest_nominal_fire_utc(
        trigger_cron, now, max_late=_lookback(max_late_hours, first_tip_utc)
    )
    if nominal is None:
        return False

    if first_tip_utc is not None:
        if nominal.astimezone(ET).date() != now.astimezone(ET).date():
            return False
        if now >= first_tip_utc - TIP_OFF_BUFFER:
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


def next_nba_scan_et(
    now: datetime | None = None,
    *,
    primary_done_today: bool | None = None,
) -> datetime:
    """Next GitHub scheduled NBA shadow run (honors weekday vs weekend ET and DST).

    Includes today's backup slot when today's primary scan has not been recorded
    (backup runs skip once the primary succeeded). ``primary_done_today=None`` reads
    the paper store.
    """
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
        if day_offset == 0:
            backup_t = WEEKDAY_BACKUP if noon.weekday() <= 4 else WEEKEND_BACKUP
            backup = datetime.combine(day, backup_t, tzinfo=ET)
            if backup > now:
                done = primary_done_today
                if done is None:
                    done = primary_scan_satisfied_for_et_date(day)
                if not done:
                    return backup
    fallback_day = now.date() + timedelta(days=1)
    return datetime.combine(fallback_day, WEEKDAY_PRIMARY, tzinfo=ET)


# --- Catch-up and staleness backup ------------------------------------------------------
# GitHub sometimes drops scheduled runs outright (all four :07 slots on Nov 3, 2026).
# A catch-up cron fires every 30 minutes; it only scans when today's ET slot has passed,
# no fresh scan exists for today, the first tip is still ahead, and the daily attempt cap
# has not been hit. Otherwise it exits before touching the Odds API.
CRON_CATCHUP = "22,52 12-23 * * *"
CATCHUP_GRACE = timedelta(minutes=20)  # let the primary slot finish before catching up
MAX_CATCHUP_SCANS_PER_DAY = 3
# Staleness guard: a game day with no scan by the backup slot + grace fails loudly.
STALE_GRACE_AFTER_BACKUP = timedelta(minutes=45)
STALE_MIN_BEFORE_TIP = timedelta(minutes=30)
STALE_CHECK_UNTIL_AFTER_TIP = timedelta(hours=4)


def is_catchup_cron(cron: str) -> bool:
    return cron.strip() == CRON_CATCHUP


def primary_slot_et(et_day: date) -> datetime:
    t = WEEKDAY_PRIMARY if et_day.weekday() <= 4 else WEEKEND_PRIMARY
    return datetime.combine(et_day, t, tzinfo=ET)


def backup_slot_et(et_day: date) -> datetime:
    t = WEEKDAY_BACKUP if et_day.weekday() <= 4 else WEEKEND_BACKUP
    return datetime.combine(et_day, t, tzinfo=ET)


def latest_live_scan_utc() -> datetime | None:
    """``generated_at`` of the last live (non-demo) NBA scan, from data/shadow."""
    import json

    from sharp_scout.nba import paths as nba_paths
    from sharp_scout.utils.kickoff import parse_kickoff_utc

    p = nba_paths.NBA_LATEST_SIGNALS_PATH
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("demo"):
        return None
    return parse_kickoff_utc(data.get("generated_at"))


def scan_fresh_for_et_date(et_day: date, *, last_scan_utc: datetime | None = None) -> bool:
    """True when a live scan already ran on this ET day (the expected once-a-day interval)."""
    last = last_scan_utc if last_scan_utc is not None else latest_live_scan_utc()
    if last is not None and last.astimezone(ET).date() == et_day:
        return True
    return primary_scan_satisfied_for_et_date(et_day)


def catchup_run_allowed(
    now: datetime,
    *,
    first_tip_utc: datetime | None,
    scan_fresh: bool,
    attempts_today: int = 0,
) -> tuple[bool, str]:
    """Decide whether a catch-up cron should run a real scan. Returns (allowed, reason)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    et_now = now.astimezone(ET)
    if first_tip_utc is None:
        return False, "no NBA games today (or ESPN unreachable)"
    if first_tip_utc.tzinfo is None:
        first_tip_utc = first_tip_utc.replace(tzinfo=timezone.utc)
    if first_tip_utc.astimezone(ET).date() != et_now.date():
        return False, "first tip is not on today's ET date"
    if scan_fresh:
        return False, "fresh scan already recorded today"
    if et_now < primary_slot_et(et_now.date()) + CATCHUP_GRACE:
        return False, "before today's primary slot + grace"
    if now >= first_tip_utc - TIP_OFF_BUFFER:
        return False, "too close to (or after) first tip"
    if attempts_today >= MAX_CATCHUP_SCANS_PER_DAY:
        return False, f"catch-up cap reached ({attempts_today}/{MAX_CATCHUP_SCANS_PER_DAY})"
    return True, "no scan yet today; catching up"


def nba_scan_stale(
    now: datetime,
    *,
    first_tip_utc: datetime | None,
    scan_fresh: bool,
) -> tuple[bool, str]:
    """True when today is a game day and no scan landed by the expected deadline."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    et_now = now.astimezone(ET)
    if first_tip_utc is None:
        return False, "no NBA games today (or ESPN unreachable)"
    if first_tip_utc.tzinfo is None:
        first_tip_utc = first_tip_utc.replace(tzinfo=timezone.utc)
    if first_tip_utc.astimezone(ET).date() != et_now.date():
        return False, "first tip is not on today's ET date"
    if scan_fresh:
        return False, "fresh scan recorded today"
    day = et_now.date()
    deadline = min(
        backup_slot_et(day) + STALE_GRACE_AFTER_BACKUP,
        first_tip_utc.astimezone(ET) - STALE_MIN_BEFORE_TIP,
    )
    deadline = max(deadline, primary_slot_et(day) + STALE_GRACE_AFTER_BACKUP)
    if et_now < deadline:
        return False, f"before staleness deadline {deadline.isoformat()}"
    if now > first_tip_utc + STALE_CHECK_UNTIL_AFTER_TIP:
        return False, "slate well under way; next check tomorrow"
    return True, f"no NBA scan today and past deadline {deadline.isoformat()}"
