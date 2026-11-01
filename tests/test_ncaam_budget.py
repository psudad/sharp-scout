from sharp_scout.ncaam.credits import (
    NCAAM_DAILY_CAP,
    can_spend,
    credits_used_today,
    record_spend,
    should_skip_snapshot,
)
from sharp_scout.scheduler.odds_credit_pause import ncaam_odds_budget_remaining


def test_budget_cap(tmp_path, monkeypatch):
    from sharp_scout.ncaam import credits as mod

    monkeypatch.setattr(mod, "NCAAM_DATA", tmp_path)
    assert can_spend(cost=2)
    for _ in range(NCAAM_DAILY_CAP // 2):
        record_spend(2)
    assert not can_spend(cost=2)
    assert ncaam_odds_budget_remaining() == 0


def test_remaining_header_floor():
    skip, reason = should_skip_snapshot(remaining_header=50)
    assert skip and reason == "global_remaining_floor"
