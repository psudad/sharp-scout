"""Model-agreement certification gate."""

from __future__ import annotations

from sharp_scout.qa.model_agreement import (
    model_agreement_block_reason,
    model_margin_disagrees,
    model_probability_disagrees,
    one_book_outlier_block_reason,
)


def test_utsa_ml_blocked_by_model_probability():
    play = {
        "market": "h2h",
        "side": "home",
        "price": 163.0,
        "p_model": 0.352,
        "p_push": 0.0,
        "model_margin": -4.1,
    }
    prob_bad, _ = model_probability_disagrees(play)
    assert prob_bad
    assert model_agreement_block_reason(play) is not None


def test_agreeing_spread_passes():
    play = {
        "market": "spreads",
        "side": "home",
        "line": -3.0,
        "price": -110,
        "p_model": 0.56,
        "model_margin": 5.0,
        "p_push": 0.0,
    }
    assert model_agreement_block_reason(play) is None


def test_one_book_outlier_blocks_betrivers_only():
    play = {
        "market": "h2h",
        "side": "home",
        "price": 163.0,
        "p_fair": 0.403,
        "p_push": 0.0,
        "book": "betrivers",
        "peer_prices_at_line": [130.0, 128.0, 135.0],
    }
    reason = one_book_outlier_block_reason(play, min_edge=0.01, price_gap=12.0)
    assert reason is not None
    assert "outlier" in reason


def test_margin_disagrees_on_home_ml():
    play = {"market": "h2h", "side": "home", "model_margin": -2.0}
    bad, msg = model_margin_disagrees(play)
    assert bad and msg