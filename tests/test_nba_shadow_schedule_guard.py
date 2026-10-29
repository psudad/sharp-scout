"""Tests for NBA shadow GitHub schedule guard (cron + intended ET slot, late starts)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sharp_scout.nba.schedule_guard import (
    CRON_WEEKDAY_BACKUP_EDT,
    CRON_WEEKDAY_BACKUP_EST,
    CRON_WEEKDAY_PRIMARY_EDT,
    CRON_WEEKDAY_PRIMARY_EST,
    CRON_WEEKEND_BACKUP_EDT,
    CRON_WEEKEND_PRIMARY_EDT,
    CRON_WEEKEND_PRIMARY_EST,
    DEFAULT_MAX_LATE_HOURS,
    WEEKDAY_PRIMARY,
    WEEKEND_PRIMARY,
    expected_cron_for_intended_slot,
    is_backup_cron,
    next_nba_scan_et,
    primary_scan_satisfied_for_et_date,
    scheduled_cron_run_allowed,
    target_time_for_et_date,
)

UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")


def _utc(y, m, d, h, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def test_weekday_edt_on_time_and_three_hours_late():
    # Tue Oct 27 2026 EDT — 3:00 PM ET = 19:00 UTC
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 10, 27, 19, 0))
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 10, 27, 22, 0))


def test_weekday_edt_four_hours_late_same_utc_day():
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 10, 27, 23, 0))
    nominal = _utc(2026, 10, 27, 19, 0)
    intended = datetime(2026, 10, 27, 15, 0, tzinfo=ET)
    assert expected_cron_for_intended_slot(intended, slot_time=WEEKDAY_PRIMARY) == CRON_WEEKDAY_PRIMARY_EDT
    assert nominal.astimezone(ET).date() == intended.date()


def test_weekday_edt_rejects_beyond_four_hours():
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 10, 28, 0, 1))


def test_weekday_edt_rejects_wrong_est_cron_same_day():
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, _utc(2026, 10, 27, 20, 0))


def test_weekday_est_after_dst_end_on_time_and_late():
    # Mon Nov 2 2026 EST — 3:00 PM ET = 20:00 UTC
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, _utc(2026, 11, 2, 20, 0))
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, _utc(2026, 11, 2, 23, 0))
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 11, 2, 19, 0))


def test_weekday_backup_edt_on_time():
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_BACKUP_EDT, _utc(2026, 10, 27, 21, 0))
    assert is_backup_cron(CRON_WEEKDAY_BACKUP_EDT)
    assert not is_backup_cron(CRON_WEEKDAY_PRIMARY_EDT)


def test_weekend_edt_on_time_and_late_before_dst_end():
    assert scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EDT, _utc(2026, 10, 31, 15, 0))
    assert scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EDT, _utc(2026, 10, 31, 18, 0))
    assert not scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EST, _utc(2026, 10, 31, 16, 0))


def test_weekend_backup_edt():
    assert scheduled_cron_run_allowed(CRON_WEEKEND_BACKUP_EDT, _utc(2026, 10, 31, 17, 0))


def test_weekend_est_after_dst_end_late_up_to_four_hours():
    assert scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EST, _utc(2026, 11, 8, 16, 0))
    assert scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EST, _utc(2026, 11, 8, 19, 59))
    assert not scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EST, _utc(2026, 11, 8, 20, 1))


def test_only_one_seasonal_cron_passes_when_both_fire_late():
    now = _utc(2026, 10, 27, 22, 0)
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, now)
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, now)


def test_max_late_hours_override():
    late = _utc(2026, 10, 27, 22, 30)
    assert scheduled_cron_run_allowed(
        CRON_WEEKDAY_PRIMARY_EDT, late, max_late_hours=DEFAULT_MAX_LATE_HOURS
    )
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, late, max_late_hours=2)


def test_unknown_cron_rejected():
    assert not scheduled_cron_run_allowed("30 14 * * *", _utc(2026, 10, 27, 19, 0))


def test_target_time_by_weekday():
    mon = datetime(2026, 10, 26, 12, 0, tzinfo=ET)
    sat = datetime(2026, 10, 31, 12, 0, tzinfo=ET)

    assert target_time_for_et_date(mon) == WEEKDAY_PRIMARY
    assert target_time_for_et_date(sat) == WEEKEND_PRIMARY


def test_next_scan_weekday_edt_after_evening_slot():
    now = datetime(2026, 10, 27, 21, 13, tzinfo=ET)
    nxt = next_nba_scan_et(now)
    assert nxt == datetime(2026, 10, 28, 15, 0, tzinfo=ET)
    assert nxt.utcoffset() == timedelta(hours=-4)


def test_next_scan_weekend_then_monday():
    sat_noon = datetime(2026, 10, 31, 12, 0, tzinfo=ET)
    assert next_nba_scan_et(sat_noon) == datetime(2026, 11, 1, 11, 0, tzinfo=ET)
    sun_afternoon = datetime(2026, 11, 1, 13, 0, tzinfo=ET)
    assert next_nba_scan_et(sun_afternoon) == datetime(2026, 11, 2, 15, 0, tzinfo=ET)


def test_primary_scan_satisfied_reads_paper_store(monkeypatch):
    day = date(2026, 10, 29)
    from sharp_scout.nba.score_model import paper as paper_mod

    monkeypatch.setattr(
        paper_mod,
        "load_paper_store",
        lambda: {
            "games": [
                {
                    "scans": [{"at": "2026-10-29T18:00:00+00:00", "after_tip": False}],
                }
            ]
        },
    )
    assert primary_scan_satisfied_for_et_date(day)
