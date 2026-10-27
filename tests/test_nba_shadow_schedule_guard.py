"""Tests for NBA shadow GitHub schedule guard (America/New_York slots, DST)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sharp_scout.nba.schedule_guard import (
    DEFAULT_TOLERANCE_MINUTES,
    scheduled_slot_matches,
    target_time_for_et_date,
)

UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")


def _utc(y, m, d, h, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def test_weekday_430pm_edt_before_dst_end():
    # Tue Oct 27 2026 — still EDT (UTC-4): 4:30 PM ET = 20:30 UTC
    assert scheduled_slot_matches(_utc(2026, 10, 27, 20, 30))
    assert not scheduled_slot_matches(_utc(2026, 10, 27, 21, 30))


def test_weekday_430pm_est_after_dst_end():
    # Mon Nov 2 2026 — EST (UTC-5): 4:30 PM ET = 21:30 UTC
    assert scheduled_slot_matches(_utc(2026, 11, 2, 21, 30))
    assert not scheduled_slot_matches(_utc(2026, 11, 2, 20, 30))


def test_weekend_11am_edt_before_dst_end():
    # Sat Oct 31 2026 EDT: 11:00 AM ET = 15:00 UTC
    assert scheduled_slot_matches(_utc(2026, 10, 31, 15, 0))
    assert not scheduled_slot_matches(_utc(2026, 10, 31, 16, 0))


def test_weekend_11am_est_after_dst_end():
    # Sun Nov 8 2026 EST: 11:00 AM ET = 16:00 UTC
    assert scheduled_slot_matches(_utc(2026, 11, 8, 16, 0))
    assert not scheduled_slot_matches(_utc(2026, 11, 8, 15, 0))


def test_wrong_slot_weekday_morning_rejected():
    # Mon Oct 27 2026 10:30 AM ET (old morning cron) — not a configured slot
    assert not scheduled_slot_matches(_utc(2026, 10, 27, 14, 30))


def test_wrong_slot_weekend_afternoon_rejected():
    assert not scheduled_slot_matches(_utc(2026, 10, 31, 20, 30))


def test_tolerance_accepts_late_github_fire():
    late = _utc(2026, 10, 27, 21, 10)  # 5:10 PM EDT Monday — within 45m of 4:30 PM
    assert scheduled_slot_matches(late, tolerance_minutes=DEFAULT_TOLERANCE_MINUTES)
    too_late = _utc(2026, 10, 27, 21, 20)  # 5:20 PM EDT — outside 45m window
    assert not scheduled_slot_matches(too_late, tolerance_minutes=DEFAULT_TOLERANCE_MINUTES)


def test_target_time_by_weekday():
    mon = datetime(2026, 10, 26, 12, 0, tzinfo=ET)
    sat = datetime(2026, 10, 31, 12, 0, tzinfo=ET)
    from sharp_scout.nba.schedule_guard import WEEKDAY_TARGET, WEEKEND_TARGET

    assert target_time_for_et_date(mon) == WEEKDAY_TARGET
    assert target_time_for_et_date(sat) == WEEKEND_TARGET
