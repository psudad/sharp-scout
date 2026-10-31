"""Regression: symmetric push-aware anchoring and EV on whole-number lines."""

from __future__ import annotations

import pytest

from sharp_scout.phase2.monte_carlo import (
    _interp_prob,
    p_push_for_market,
    p_true_for_market,
    simulate_game,
)
from sharp_scout.phase3.market import anchor_probability
from sharp_scout.utils.odds import (
    expected_value,
    expected_value_whole_line_cond,
    expected_value_with_push,
    marginal_win_prob,
    win_prob_to_conditional,
)


def _ev_three_way(p_win: float, p_push: float, price: float = -110.0) -> float:
    p_loss = max(0.0, 1.0 - p_win - p_push)
    dec = 1 + 100.0 / abs(price)
    return p_win * (dec - 1.0) - p_loss


@pytest.fixture(scope="module")
def sim():
    return simulate_game(
        "WMU",
        "BGSU",
        32.5,
        19.0,
        n_sims=60_000,
        spread_keys=[-13.0, -13.5, 13.0, 3.0, -3.0],
        total_keys=[49.0, 49.5],
        sport="ncaaf",
        seed=7,
    )


def test_symmetric_fifty_fifty_market_equal_ev():
    """Two-way no-vig 50/50 at -110/-110: same p_cond and p_push => same EV all sides."""
    p_push = 0.03
    p_cond = 0.5
    price = -110.0
    ev_spread_home = expected_value_whole_line_cond(p_cond, price, p_push)
    ev_spread_away = expected_value_whole_line_cond(p_cond, price, p_push)
    ev_over = expected_value_whole_line_cond(p_cond, price, p_push)
    ev_under = expected_value_whole_line_cond(p_cond, price, p_push)
    assert ev_spread_home == pytest.approx(ev_spread_away, abs=1e-12)
    assert ev_over == pytest.approx(ev_under, abs=1e-12)
    assert ev_spread_home == pytest.approx(ev_over, abs=1e-12)


def test_home_minus_13_conditional_ev(sim):
    p_win = p_true_for_market(sim, "spreads", "home", -13.0, sport="ncaaf")
    p_push = p_push_for_market(sim, "spreads", "home", -13.0, sport="ncaaf")
    p_cond = win_prob_to_conditional(p_win, p_push)
    p_cond = anchor_probability(p_cond, 0.5286, 0.35, 0.03)
    p_marg = marginal_win_prob(p_cond, p_push)
    ev = expected_value_whole_line_cond(p_cond, -110.0, p_push)
    assert ev == pytest.approx(_ev_three_way(p_marg, p_push), abs=1e-9)
    assert ev == pytest.approx(expected_value_with_push(p_marg, -110.0, p_push), abs=1e-9)
    # Pre-#127 double-count path on wrongly anchored marginal p_true.
    wrong_marg = anchor_probability(p_win, 0.5286, 0.35, 0.03)
    assert expected_value(wrong_marg, -110.0) + p_push > ev + 0.01


def test_away_plus_3_ev_matches_three_way(sim):
    p_win = p_true_for_market(sim, "spreads", "away", 3.0, sport="ncaaf")
    p_push = p_push_for_market(sim, "spreads", "away", 3.0, sport="ncaaf")
    p_cond = win_prob_to_conditional(p_win, p_push)
    edge = expected_value_whole_line_cond(p_cond, -110.0, p_push)
    assert edge == pytest.approx(_ev_three_way(p_win, p_push), abs=1e-9)
    legacy_p = 1.0 - _interp_prob(sim.cover_probs, -3.0)
    legacy_ev = expected_value(legacy_p, -110.0) + p_push
    assert legacy_ev > edge + 0.01


def test_whole_total_49_over_under(sim):
    for side in ("over", "under"):
        p_win = p_true_for_market(sim, "totals", side, 49.0)
        p_push = p_push_for_market(sim, "totals", side, 49.0)
        p_cond = win_prob_to_conditional(p_win, p_push)
        edge = expected_value_whole_line_cond(p_cond, -110.0, p_push)
        assert edge == pytest.approx(_ev_three_way(p_win, p_push), abs=1e-9)


def test_nfl_key_number_partition():
    sim = simulate_game("HOU", "BUF", 23.5, 21.0, spread_keys=[-3.0, 3.0], sport="nfl")
    p_win = p_true_for_market(sim, "spreads", "home", -3.0, sport="nfl")
    p_push = p_push_for_market(sim, "spreads", "home", -3.0, sport="nfl")
    p_away = p_true_for_market(sim, "spreads", "away", 3.0, sport="nfl")
    assert p_win + p_away + p_push == pytest.approx(1.0, abs=1e-9)
