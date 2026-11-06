from datetime import datetime
from zoneinfo import ZoneInfo

from sharp_scout.ncaam.rules import (
    RULES,
    anchor_k_spread,
    apply_daily_cap,
    stake_units,
    candidate_ev,
    display_confidence,
)
from sharp_scout.utils.odds import expected_value_with_push

ET = ZoneInfo("America/New_York")


def test_anchor_k_before_dec1():
    k = anchor_k_spread(datetime(2026, 11, 15, 12, tzinfo=ET))
    assert k == RULES.anchor_k_early


def test_anchor_k_from_dec1():
    k = anchor_k_spread(datetime(2026, 12, 1, tzinfo=ET))
    assert k == RULES.anchor_k_after_dec1


def test_stake_caps():
    assert stake_units(ev=0.04, beat_open=False, units_already_today=0) == 1.0
    assert stake_units(ev=0.07, beat_open=True, units_already_today=0) == 1.5
    # Daily unit ceiling removed: high units_already_today no longer shrinks stake.
    assert stake_units(ev=0.07, beat_open=True, units_already_today=7.5) == 1.5


def test_no_daily_play_or_unit_cap():
    cands = [
        {"event_id": str(i), "espn_id": str(i), "ev": 0.1 - i * 0.001, "et_day": "2026-11-02", "side": "home", "line": -3.0}
        for i in range(12)
    ]
    picked = apply_daily_cap(cands, et_day=datetime(2026, 11, 2).date())
    assert len(picked) == 12
    assert all(p["units"] > 0 for p in picked)
    # Even when 8 plays / 8u are already locked, more qualifying picks still post.
    more = apply_daily_cap(cands, et_day=datetime(2026, 11, 2).date(), already_plays=8, already_units=8.0)
    assert len(more) == 12


def test_ev_matches_utils():
    p = 0.55
    price = -110
    assert candidate_ev(p, price, 0.0) == expected_value_with_push(p, price, 0.0)


def test_confidence_display_cap():
    assert display_confidence(0.95) == 0.80
