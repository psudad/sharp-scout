"""Tests for NBA shadow GitHub schedule guard (cron + intended ET slot, late starts)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sharp_scout.nba.schedule_guard import (
    CRON_WEEKDAY_EDT,
    CRON_WEEKDAY_EST,
    CRON_WEEKEND_EDT,
    CRON_WEEKEND_EST,
    DEFAULT_MAX_LATE_HOURS,
    expected_cron_for_intended_slot,
    next_nba_scan_et,
    scheduled_cron_run_allowed,
    target_time_for_et_date,
)

UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")


def _utc(y, m, d, h, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def test_weekday_edt_on_time_and_three_hours_late():
    # Tue Oct 27 2026 EDT — 4:30 PM ET = 20:30 UTC
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_EDT, _utc(2026, 10, 27, 20, 30))
    # 3h late (7:30 PM ET), still Monday UTC calendar day
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_EDT, _utc(2026, 10, 27, 23, 30))


def test_weekday_edt_four_hours_late_crosses_utc_midnight():
    # Nominal Mon Oct 27 20:30 UTC; start Tue Oct 28 00:30 UTC (4h late)
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_EDT, _utc(2026, 10, 28, 0, 30))
    # Intended slot stays Monday ET (not misread as Tuesday weekday)
    nominal = _utc(2026, 10, 27, 20, 30)
    intended = datetime(2026, 10, 27, 16, 30, tzinfo=ET)
    assert expected_cron_for_intended_slot(intended) == CRON_WEEKDAY_EDT
    assert nominal.astimezone(ET).date() == intended.date()


def test_weekday_edt_rejects_beyond_four_hours():
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_EDT, _utc(2026, 10, 28, 0, 31))


def test_weekday_edt_rejects_wrong_est_cron_same_day():
    # Mon Oct 27 2026 — 21:30 UTC is 5:30 PM EDT; EST cron must not run
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_EST, _utc(2026, 10, 27, 21, 30))
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_EST, _utc(2026, 10, 28, 0, 0))


def test_weekday_est_after_dst_end_on_time_and_late():
    # Mon Nov 2 2026 EST — 4:30 PM ET = 21:30 UTC
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_EST, _utc(2026, 11, 2, 21, 30))
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_EST, _utc(2026, 11, 3, 0, 30))
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_EDT, _utc(2026, 11, 2, 20, 30))


def test_weekend_edt_on_time_and_late_before_dst_end():
    assert scheduled_cron_run_allowed(CRON_WEEKEND_EDT, _utc(2026, 10, 31, 15, 0))
    assert scheduled_cron_run_allowed(CRON_WEEKEND_EDT, _utc(2026, 10, 31, 18, 30))
    assert not scheduled_cron_run_allowed(CRON_WEEKEND_EST, _utc(2026, 10, 31, 16, 0))


def test_weekend_est_after_dst_end_late_up_to_four_hours():
    assert scheduled_cron_run_allowed(CRON_WEEKEND_EST, _utc(2026, 11, 8, 16, 0))
    assert scheduled_cron_run_allowed(CRON_WEEKEND_EST, _utc(2026, 11, 8, 19, 59))
    assert not scheduled_cron_run_allowed(CRON_WEEKEND_EST, _utc(2026, 11, 8, 20, 1))


def test_only_one_seasonal_cron_passes_when_both_fire_late():
    now = _utc(2026, 10, 27, 23, 0)
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_EDT, now)
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_EST, now)


def test_max_late_hours_override():
    late = _utc(2026, 10, 27, 23, 30)
    assert scheduled_cron_run_allowed(
        CRON_WEEKDAY_EDT, late, max_late_hours=DEFAULT_MAX_LATE_HOURS
    )
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_EDT, late, max_late_hours=2)


def test_unknown_cron_rejected():
    assert not scheduled_cron_run_allowed("30 14 * * *", _utc(2026, 10, 27, 20, 30))


def test_target_time_by_weekday():
    mon = datetime(2026, 10, 26, 12, 0, tzinfo=ET)
    sat = datetime(2026, 10, 31, 12, 0, tzinfo=ET)
    from sharp_scout.nba.schedule_guard import WEEKDAY_TARGET, WEEKEND_TARGET

    assert target_time_for_et_date(mon) == WEEKDAY_TARGET
    assert target_time_for_et_date(sat) == WEEKEND_TARGET


def test_next_scan_weekday_edt_after_evening_slot():
    # Tue Oct 27 2026 9:13 PM EDT — today's 4:30 PM passed; next is Wed 4:30 PM (not 5:30 EST cron).
    now = datetime(2026, 10, 27, 21, 13, tzinfo=ET)
    nxt = next_nba_scan_et(now)
    assert nxt == datetime(2026, 10, 28, 16, 30, tzinfo=ET)
    assert nxt.utcoffset() == timedelta(hours=-4)


def test_next_scan_weekend_then_monday():
    # Sat Oct 31 2026 noon EDT — morning slot passed; next is Sun 11 AM.
    sat_noon = datetime(2026, 10, 31, 12, 0, tzinfo=ET)
    assert next_nba_scan_et(sat_noon) == datetime(2026, 11, 1, 11, 0, tzinfo=ET)
    # Sun 1 PM — next is Mon 4:30 PM.
    sun_afternoon = datetime(2026, 11, 1, 13, 0, tzinfo=ET)
    assert next_nba_scan_et(sun_afternoon) == datetime(2026, 11, 2, 16, 30, tzinfo=ET)


def test_late_start_uses_intended_slot_date_for_dst_not_delayed_clock():
    # Nominal Mon 20:30 UTC; delayed start Tue 00:30 UTC (4h late). Offset must follow
    # Monday 4:30 PM ET, not whatever wall clock GitHub reports at job start.
    now = _utc(2026, 10, 28, 0, 30)
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_EDT, now)
    intended = datetime(2026, 10, 27, 16, 30, tzinfo=ET)
    assert expected_cron_for_intended_slot(intended) == CRON_WEEKDAY_EDT
    # EST line for the same intended slot would be wrong even when late
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_EST, now)
