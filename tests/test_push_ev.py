"""Regression: push-aware EV must not double-count push mass."""

from __future__ import annotations

import pytest

from sharp_scout.phase2.monte_carlo import (
    _interp_prob,
    p_push_for_market,
    p_true_for_market,
    simulate_game,
)
from sharp_scout.phase3.market import anchor_probability
from sharp_scout.utils.odds import expected_value, expected_value_with_push


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


def test_home_minus_13_no_double_push_in_ev(sim):
    p_win = p_true_for_market(sim, "spreads", "home", -13.0, sport="ncaaf")
    p_push = p_push_for_market(sim, "spreads", "home", -13.0, sport="ncaaf")
    p_true = anchor_probability(p_win, 0.5286, 0.35, 0.03)
    ev_home_rule = expected_value(p_true, -110.0)
    ev_double = expected_value(p_true, -110.0) + p_push
    assert ev_double - ev_home_rule == pytest.approx(p_push, abs=0.001)
    # Win-only three-way EV is lower; home spread uses p_true EV without extra +p_push.
    assert ev_home_rule > expected_value_with_push(p_win, -110.0, p_push)


def test_away_plus_3_ev_matches_three_way(sim):
    p_win = p_true_for_market(sim, "spreads", "away", 3.0, sport="ncaaf")
    p_push = p_push_for_market(sim, "spreads", "away", 3.0, sport="ncaaf")
    edge = expected_value_with_push(p_win, -110.0, p_push)
    assert edge == pytest.approx(_ev_three_way(p_win, p_push), abs=1e-9)
    legacy_p = 1.0 - _interp_prob(sim.cover_probs, -3.0)
    legacy_ev = expected_value(legacy_p, -110.0) + p_push
    assert legacy_ev > edge + 0.01


def test_whole_total_49_over_under(sim):
    for side in ("over", "under"):
        p_win = p_true_for_market(sim, "totals", side, 49.0)
        p_push = p_push_for_market(sim, "totals", side, 49.0)
        edge = expected_value_with_push(p_win, -110.0, p_push)
        assert edge == pytest.approx(_ev_three_way(p_win, p_push), abs=1e-9)


def test_nfl_key_number_partition():
    sim = simulate_game("HOU", "BUF", 23.5, 21.0, spread_keys=[-3.0, 3.0], sport="nfl")
    p_win = p_true_for_market(sim, "spreads", "home", -3.0, sport="nfl")
    p_push = p_push_for_market(sim, "spreads", "home", -3.0, sport="nfl")
    p_away = p_true_for_market(sim, "spreads", "away", 3.0, sport="nfl")
    assert p_win + p_away + p_push == pytest.approx(1.0, abs=1e-9)
