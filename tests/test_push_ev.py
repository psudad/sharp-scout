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


def _symmetric_pick_em_event() -> dict:
    """Pinnacle pick'em spread and whole total, both sides -110 (no-vig 50/50)."""
    return {
        "event_id": "sym-push",
        "home_team": "H",
        "away_team": "A",
        "bookmakers": {
            "pinnacle": {
                "key": "pinnacle",
                "is_sharp": True,
                "markets": {
                    "spreads": [
                        {"side": "home", "price": -110, "point": 0.0},
                        {"side": "away", "price": -110, "point": 0.0},
                    ],
                    "totals": [
                        {"side": "over", "price": -110, "point": 48.0},
                        {"side": "under", "price": -110, "point": 48.0},
                    ],
                },
            },
        },
    }


def _symmetric_centered_sim(*, n_sims: int = 80_000, seed: int = 7):
    """Sim centered on pick'em / total 48 with matched push mass on both sides."""
    import numpy as np

    from sharp_scout.phase2.monte_carlo import GameSimResult

    rng = np.random.default_rng(seed)
    pairs = [(24, 24), (25, 23), (23, 25), (23, 23), (25, 25)]
    weights = np.array([0.12, 0.22, 0.22, 0.22, 0.22], dtype=float)
    weights /= weights.sum()
    idx = rng.choice(len(pairs), size=n_sims, p=weights)
    home_scores = np.array([pairs[i][0] for i in idx])
    away_scores = np.array([pairs[i][1] for i in idx])
    margin = home_scores - away_scores
    total = home_scores + away_scores
    return GameSimResult(
        home_team="H",
        away_team="A",
        mu_home=24.0,
        mu_away=24.0,
        n_sims=n_sims,
        model_spread=0.0,
        model_total=48.0,
        p_home_win=float(np.mean(margin > 0)),
        p_away_win=float(np.mean(margin < 0)),
        p_push_ml=float(np.mean(margin == 0)),
        cover_probs={0.0: float(np.mean(margin > 0))},
        over_probs={48.0: float(np.mean(total > 48))},
        home_scores=home_scores,
        away_scores=away_scores,
    )


def test_discover_edges_symmetric_whole_line_equal_ev():
    """End-to-end: symmetric -110/-110 whole spread/total → equal EV on both sides."""
    from sharp_scout.phase3.market import discover_edges

    sim = _symmetric_centered_sim()
    edges = discover_edges(
        _symmetric_pick_em_event(),
        sim,
        ev_threshold=-10.0,
        sport="ncaaf",
    )
    by_side = {(e.market, e.side): e for e in edges}
    for key in (
        ("spreads", "home"),
        ("spreads", "away"),
        ("totals", "over"),
        ("totals", "under"),
    ):
        assert key in by_side, f"missing edge {key}"
        assert by_side[key].p_fair == pytest.approx(0.5, abs=1e-4)

    ev_home = by_side[("spreads", "home")].edge
    ev_away = by_side[("spreads", "away")].edge
    ev_over = by_side[("totals", "over")].edge
    ev_under = by_side[("totals", "under")].edge
    assert ev_home == pytest.approx(ev_away, abs=0.001)
    assert ev_over == pytest.approx(ev_under, abs=0.001)
