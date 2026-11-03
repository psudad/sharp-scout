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
    CRON_WEEKEND_BACKUP_EST,
    CRON_WEEKEND_PRIMARY_EDT,
    CRON_WEEKEND_PRIMARY_EST,
    DEFAULT_MAX_LATE_HOURS,
    TIP_OFF_BUFFER,
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
    # Tue Oct 27 2026 EDT — 1:07 PM ET = 17:07 UTC
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 10, 27, 17, 7))
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 10, 27, 20, 7))


def test_weekday_edt_four_hours_late_same_utc_day():
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 10, 27, 21, 7))
    nominal = _utc(2026, 10, 27, 17, 7)
    intended = datetime(2026, 10, 27, 13, 7, tzinfo=ET)
    assert expected_cron_for_intended_slot(intended, slot_time=WEEKDAY_PRIMARY) == CRON_WEEKDAY_PRIMARY_EDT
    assert nominal.astimezone(ET).date() == intended.date()


def test_weekday_edt_rejects_beyond_four_hours_without_tip():
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 10, 27, 21, 8))


def test_weekday_edt_rejects_wrong_est_cron_same_day():
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, _utc(2026, 10, 27, 18, 7))


def test_weekday_est_after_dst_end_on_time_and_late():
    # Mon Nov 2 2026 EST — 1:07 PM ET = 18:07 UTC
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, _utc(2026, 11, 2, 18, 7))
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, _utc(2026, 11, 2, 21, 0))
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, _utc(2026, 11, 2, 17, 7))


def test_weekday_backup_edt_on_time():
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_BACKUP_EDT, _utc(2026, 10, 27, 20, 7))
    assert is_backup_cron(CRON_WEEKDAY_BACKUP_EDT)
    assert not is_backup_cron(CRON_WEEKDAY_PRIMARY_EDT)


def test_weekend_edt_on_time_and_late_before_dst_end():
    assert scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EDT, _utc(2026, 10, 31, 13, 7))
    assert scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EDT, _utc(2026, 10, 31, 16, 0))
    assert not scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EST, _utc(2026, 10, 31, 14, 7))


def test_weekend_backup_edt():
    assert scheduled_cron_run_allowed(CRON_WEEKEND_BACKUP_EDT, _utc(2026, 10, 31, 15, 7))


def test_weekend_est_after_dst_end_late_up_to_four_hours():
    assert scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EST, _utc(2026, 11, 8, 14, 7))
    assert scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EST, _utc(2026, 11, 8, 18, 6))
    assert not scheduled_cron_run_allowed(CRON_WEEKEND_PRIMARY_EST, _utc(2026, 11, 8, 18, 8))


def test_only_one_seasonal_cron_passes_when_both_fire_late():
    now = _utc(2026, 10, 27, 20, 0)
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, now)
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, now)


def test_max_late_hours_override():
    late = _utc(2026, 10, 27, 20, 30)
    assert scheduled_cron_run_allowed(
        CRON_WEEKDAY_PRIMARY_EDT, late, max_late_hours=DEFAULT_MAX_LATE_HOURS
    )
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, late, max_late_hours=2)


def test_late_start_allowed_until_first_tip():
    # Mon Nov 2 2026 EST: first tip 7:00 PM ET = 00:00 UTC Nov 3.
    tip = _utc(2026, 11, 3, 0, 0)
    # 5h33m late (6:40 PM ET) — beyond the 4h fallback, but still before the first tip.
    late = _utc(2026, 11, 2, 23, 40)
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, late)
    assert scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EST, late, first_tip_utc=tip)
    # Inside the pre-tip buffer and after tip: rejected.
    assert not scheduled_cron_run_allowed(
        CRON_WEEKDAY_PRIMARY_EST, tip - TIP_OFF_BUFFER, first_tip_utc=tip
    )
    assert not scheduled_cron_run_allowed(
        CRON_WEEKDAY_PRIMARY_EST, _utc(2026, 11, 3, 0, 30), first_tip_utc=tip
    )
    # Wrong seasonal line is still rejected when the tip is known.
    assert not scheduled_cron_run_allowed(CRON_WEEKDAY_PRIMARY_EDT, late, first_tip_utc=tip)


def test_first_tip_gate_blocks_run_before_lateness_limit_when_games_started():
    # Weekend matinee: tip 12:00 PM ET Sat Nov 7 (EST) = 17:00 UTC; backup on time at 16:07 UTC ok,
    # but a backup arriving at 17:05 UTC (inside the 4h fallback) is blocked by the tip.
    tip = _utc(2026, 11, 7, 17, 0)
    assert scheduled_cron_run_allowed(CRON_WEEKEND_BACKUP_EST, _utc(2026, 11, 7, 16, 7), first_tip_utc=tip)
    assert not scheduled_cron_run_allowed(
        CRON_WEEKEND_BACKUP_EST, _utc(2026, 11, 7, 17, 5), first_tip_utc=tip
    )


def test_first_tip_gate_rejects_previous_et_day_slot():
    # Backup cron 21:07 UTC Mon arriving 05:30 UTC Tue (00:30 ET Tue) — different ET day.
    tip = _utc(2026, 11, 4, 0, 0)
    assert not scheduled_cron_run_allowed(
        CRON_WEEKDAY_BACKUP_EST, _utc(2026, 11, 3, 5, 30), first_tip_utc=tip
    )


def test_unknown_cron_rejected():
    assert not scheduled_cron_run_allowed("30 14 * * *", _utc(2026, 10, 27, 19, 0))
    assert not scheduled_cron_run_allowed("0 20 * * 1-5", _utc(2026, 11, 2, 20, 0))


def test_target_time_by_weekday():
    mon = datetime(2026, 10, 26, 12, 0, tzinfo=ET)
    sat = datetime(2026, 10, 31, 12, 0, tzinfo=ET)

    assert target_time_for_et_date(mon) == WEEKDAY_PRIMARY
    assert target_time_for_et_date(sat) == WEEKEND_PRIMARY


def test_next_scan_weekday_edt_after_evening_slot():
    now = datetime(2026, 10, 27, 21, 13, tzinfo=ET)
    nxt = next_nba_scan_et(now, primary_done_today=True)
    assert nxt == datetime(2026, 10, 28, 13, 7, tzinfo=ET)
    assert nxt.utcoffset() == timedelta(hours=-4)


def test_next_scan_weekend_then_monday():
    sat_noon = datetime(2026, 10, 31, 12, 0, tzinfo=ET)
    assert next_nba_scan_et(sat_noon, primary_done_today=False) == datetime(2026, 11, 1, 9, 7, tzinfo=ET)
    sun_afternoon = datetime(2026, 11, 1, 13, 0, tzinfo=ET)
    assert next_nba_scan_et(sun_afternoon, primary_done_today=False) == datetime(
        2026, 11, 2, 13, 7, tzinfo=ET
    )


def test_next_scan_shows_same_day_backup_when_primary_missing():
    after_primary = datetime(2026, 11, 2, 14, 0, tzinfo=ET)
    assert next_nba_scan_et(after_primary, primary_done_today=False) == datetime(
        2026, 11, 2, 16, 7, tzinfo=ET
    )
    assert next_nba_scan_et(after_primary, primary_done_today=True) == datetime(
        2026, 11, 3, 13, 7, tzinfo=ET
    )


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
