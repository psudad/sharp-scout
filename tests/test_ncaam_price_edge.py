"""Unit tests for NCAAM price-edge gate math."""

from sharp_scout.ncaam.price_edge import (
    diagnostic_row,
    price_edge_ev,
    price_edge_qualifies,
    split_lock_ev_parts,
)
from sharp_scout.utils.odds import expected_value, expected_value_with_push, win_prob_to_conditional


def test_price_edge_simple_favorite():
    p_fair = 0.55
    price = -110
    assert price_edge_ev(p_fair, price) == expected_value(p_fair, price)
    assert price_edge_qualifies(p_fair, price, min_edge=0.01)


def test_missing_pinnacle_fair_does_not_qualify():
    assert price_edge_ev(None, -110) is None
    assert not price_edge_qualifies(None, -110, min_edge=0.01)


def test_push_aware_whole_number_spread():
    p_fair = 0.50
    p_push = 0.04
    price = -110
    p_cond = win_prob_to_conditional(p_fair, p_push)
    want = expected_value_with_push(p_cond, price, p_push)
    assert price_edge_ev(p_fair, price, p_push) == want
    # Push refund lifts EV vs naive p_fair×dec−1 on a coin flip at -110.
    assert price_edge_ev(p_fair, price, p_push) > expected_value(p_fair, price)


def test_split_matches_review_formulas():
    p_fair, p_true, price = 0.519, 0.534, -105
    price_part, model_part = split_lock_ev_parts(p_fair, p_true, price)
    assert price_part is not None and model_part is not None
    dec = 1 + 100 / 105
    assert abs(price_part - (p_fair * dec - 1)) < 1e-9
    assert abs(model_part - ((p_true - p_fair) * dec)) < 1e-9


def test_diagnostic_row_never_invents_fair():
    row = diagnostic_row(
        {
            "espn_id": "1",
            "market": "spreads",
            "side": "home",
            "line": -3.0,
            "price": -110,
            "p_true": 0.56,
            "p_fair": None,
        },
        min_edge=0.01,
    )
    assert row["price_edge"] is None
    assert row["would_pass_gate"] is False
