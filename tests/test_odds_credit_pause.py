"""Odds API credit pause gates (through Nov 6 2026 ET) and Nov 1 NFL exception."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sharp_scout.scheduler.odds_credit_pause import (
    NOV1_NFL_PREGAME_CRON,
    ODDS_CREDIT_RESUME_ET_DATE,
    nov1_2026_nfl_sunday_pregame_allowed,
    pregame_scheduled_allowed,
    scheduled_odds_pause_active,
)

UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")


def _utc(y, m, d, h, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def test_pause_active_before_nov6_et():
    assert scheduled_odds_pause_active(_utc(2026, 11, 6, 4, 59))  # 23:59 ET Nov 5 (EST)
    assert not scheduled_odds_pause_active(_utc(2026, 11, 6, 5, 0))  # 00:00 ET Nov 6 (EST)


def test_pregame_blocked_during_pause_except_nov1():
    proceed, nov1 = pregame_scheduled_allowed("5,35 * * * *", _utc(2026, 10, 27, 12, 0))
    assert not proceed and not nov1


def test_nov1_exception_on_time_est():
    # Nov 1 2026 09:00 ET (EST) = 14:00 UTC Sunday
    assert nov1_2026_nfl_sunday_pregame_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 11, 1, 14, 0))
    proceed, nov1 = pregame_scheduled_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 11, 1, 14, 0))
    assert proceed and nov1


def test_nov1_exception_three_hours_late():
    assert nov1_2026_nfl_sunday_pregame_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 11, 1, 17, 0))
    proceed, nov1 = pregame_scheduled_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 11, 1, 17, 0))
    assert proceed and nov1


def test_nov1_exception_four_hours_late_boundary():
    assert nov1_2026_nfl_sunday_pregame_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 11, 1, 18, 0))
    assert not nov1_2026_nfl_sunday_pregame_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 11, 1, 18, 1))


def test_nov1_wrong_cron_or_date_rejected():
    assert not nov1_2026_nfl_sunday_pregame_allowed("0 15 * * 0", _utc(2026, 11, 1, 15, 0))
    # Same cron on a different Sunday after billing resume must not qualify
    assert not nov1_2026_nfl_sunday_pregame_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 11, 8, 14, 0))


def test_nov1_late_start_keeps_intended_sunday_not_utc_monday():
    # Nominal Sun Nov 1 14:00 UTC; delayed to Mon Nov 2 01:00 UTC (>4h) — reject
    assert not nov1_2026_nfl_sunday_pregame_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 11, 2, 1, 0))
    # 3h late still Nov 1 ET afternoon
    now = _utc(2026, 11, 1, 17, 0)
    assert nov1_2026_nfl_sunday_pregame_allowed(NOV1_NFL_PREGAME_CRON, now)
    assert now.astimezone(ET).date().year == 2026 and now.astimezone(ET).month == 11
    assert now.astimezone(ET).day == 1


def test_after_resume_normal_pregame_schedule_allowed():
    proceed, nov1 = pregame_scheduled_allowed("5,35 * * * *", _utc(2026, 11, 6, 12, 0))
    assert proceed and not nov1


def test_nov1_cron_on_other_sundays_during_pause_rejected():
    # Oct 26 2026 Sunday — same cron line, wrong intended ET date
    assert not nov1_2026_nfl_sunday_pregame_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 10, 26, 14, 0))
    proceed, nov1 = pregame_scheduled_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 10, 26, 14, 0))
    assert not proceed and not nov1


def test_nov1_slot_uses_est_after_dst_ends_same_morning():
    # DST ends Nov 1 2026 at 02:00 ET; 09:00 ET is EST → 14:00 UTC
    slot = datetime(2026, 11, 1, 9, 0, tzinfo=ET)
    assert slot.utcoffset() == timedelta(hours=-5)
    assert nov1_2026_nfl_sunday_pregame_allowed(NOV1_NFL_PREGAME_CRON, _utc(2026, 11, 1, 14, 0))
