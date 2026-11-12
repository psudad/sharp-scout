"""Unit tests for NCAAM price-edge gate math."""

from sharp_scout.config import get_settings
from sharp_scout.ncaam.price_edge import (
    diagnostic_row,
    filter_day_picks_for_price_edge,
    price_edge_ev,
    price_edge_filter_reason,
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


def test_config_gate_on_by_default():
    assert get_settings().ncaam_price_edge_gate_enabled is True
    assert get_settings().ncaam_price_edge_min == 0.01


def test_gate_blocks_below_min_allows_at_threshold():
    # -110 needs ~52.38% implied; 0.53 fair → small positive edge
    assert price_edge_qualifies(0.53, -110, min_edge=0.01)
    assert price_edge_filter_reason(0.53, -110, min_edge=0.01) is None
    # 0.51 at -110 is below fair → negative price edge
    assert not price_edge_qualifies(0.51, -110, min_edge=0.01)
    reason = price_edge_filter_reason(0.51, -110, min_edge=0.01)
    assert reason is not None and reason.startswith("price_edge_below_min")


def test_filter_day_picks_marks_filtered_out():
    picks = [
        {"espn_id": "ok", "p_fair": 0.55, "p_true": 0.56, "price": -110, "p_push": 0.0},
        {"espn_id": "low", "p_fair": 0.51, "p_true": 0.56, "price": -110, "p_push": 0.0},
        {"espn_id": "nofair", "p_fair": None, "p_true": 0.56, "price": -110, "p_push": 0.0},
    ]
    locked, rows = filter_day_picks_for_price_edge(picks, gate_enabled=True, min_edge=0.01)
    assert [p["espn_id"] for p in locked] == ["ok"]
    by_id = {r["espn_id"]: r for r in rows}
    assert by_id["ok"]["filtered_out"] is False and by_id["ok"]["would_post"] is True
    assert by_id["low"]["filtered_out"] is True and by_id["low"]["filter_reason"].startswith("price_edge_below_min")
    assert by_id["nofair"]["filtered_out"] is True and by_id["nofair"]["filter_reason"] == "missing_pinnacle_fair"


def test_gate_off_posts_all_but_still_diagnoses():
    picks = [{"espn_id": "low", "p_fair": 0.51, "p_true": 0.56, "price": -110, "p_push": 0.0}]
    locked, rows = filter_day_picks_for_price_edge(picks, gate_enabled=False, min_edge=0.01)
    assert len(locked) == 1
    assert rows[0]["filtered_out"] is False
    assert rows[0]["would_pass_gate"] is False
    assert rows[0]["would_post"] is True


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
    assert row["filtered_out"] is True
    assert row["filter_reason"] == "missing_pinnacle_fair"
