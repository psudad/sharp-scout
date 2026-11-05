"""Nov 2026 high-confidence rules: Action PRO tier, public-side veto, bettable books, NFL price-only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sharp_scout.data.action_network import parse_pro_report
from sharp_scout.data.splits_board import build_market_board
from sharp_scout.qa.gate import _duplicate_p_true_clusters
from sharp_scout.qa.pro_tier import build_pro_tier_candidates, pro_tier_reasons
from sharp_scout.qa.product_gate import evaluate_product_play, select_certified_plays

pytestmark = pytest.mark.hc_rules

SHARP = {"type": "sharp_money", "strength": 0.8, "steam_moves": 4, "reverse_line_moves": 2, "edge": None}
MODEL = {"type": "power_rating_edge", "strength": 0.6, "steam_moves": None, "reverse_line_moves": None, "edge": 3.5}


def _board(*, market="total", side="over", signals=(SHARP, MODEL), tickets=0.40, home="ALA", away="UGA"):
    sides = ("over", "under") if market == "total" else ("home", "away")
    block = {f"{s}_bet_pct": (tickets if s == side else 1 - tickets) for s in sides}
    block.update({f"{s}_money_pct": 0.5 for s in sides})
    block["current_line"] = 52.5
    block["pro_signals"] = {s: (list(signals) if s == side else []) for s in sides}
    mb = build_market_board(block, market=market, home_team=home, away_team=away)
    return {"home_team": home, "away_team": away, "available": True, "markets": {market: mb}}


def _event(*, fd_over=-110, pin=(-110, -110), line=52.5):
    kick = datetime.now(timezone.utc) + timedelta(hours=20)
    return {
        "event_id": "e1",
        "home_team": "ALA",
        "away_team": "UGA",
        "commence_time": kick,
        "bookmakers": {
            "pinnacle": {
                "markets": {
                    "totals": [
                        {"side": "over", "price": pin[0], "point": line},
                        {"side": "under", "price": pin[1], "point": line},
                    ]
                }
            },
            "fanduel": {
                "markets": {
                    "totals": [
                        {"side": "over", "price": fd_over, "point": line},
                        {"side": "under", "price": -110, "point": line},
                    ]
                }
            },
            "draftkings": {
                "markets": {"totals": [{"side": "over", "price": +105, "point": line}]}
            },
        },
    }


def test_parse_pro_report_flattens_signals():
    out = parse_pro_report(
        {
            "total": {
                "over": [
                    {
                        "signal_type": "sharp_money",
                        "strength": 0.9,
                        "meta": {"steam_moves": 2, "reverse_line_moves": 5},
                    }
                ]
            },
            "spread": {"home": [{"signal_type": "power_rating_edge", "meta": {"edge": 4.1}}]},
        }
    )
    assert out["total"]["over"][0]["reverse_line_moves"] == 5
    assert out["total"]["under"] == []
    assert out["spread"]["home"][0]["edge"] == 4.1


def test_pro_tier_requires_sharp_and_model_edge():
    assert pro_tier_reasons([SHARP, MODEL]) == []
    assert pro_tier_reasons([SHARP])
    assert pro_tier_reasons([MODEL])
    assert pro_tier_reasons([SHARP, {**MODEL, "edge": 2.5}])


def test_pro_candidates_only_at_bettable_book_on_signal_side():
    cands = build_pro_tier_candidates([_event()], [_board()], sport="ncaaf")
    assert [(c["book"], c["side"]) for c in cands] == [("fanduel", "over")]
    c = cands[0]
    assert c["pro_confirmed"] and c["filter_passed"] and c["tier"] == "play"
    assert c["p_fair"] == pytest.approx(0.5, abs=1e-3)
    assert "Sharp Action" in c["rationale"]


def test_pro_candidates_not_built_for_nfl_or_spreads():
    assert build_pro_tier_candidates([_event()], [_board()], sport="nfl") == []


def test_pro_tier_play_certifies_and_ranks_first():
    board = _board()
    pro = build_pro_tier_candidates([_event()], [board], sport="ncaaf")[0]
    lane = {**pro, "pro_confirmed": None, "edge": 0.09, "flags": {"money_split": True}, "sharp_book": "pinnacle"}
    payload = {"signals": [pro, lane], "split_boards": [board]}
    r = evaluate_product_play(pro, signals=payload, sport="ncaaf")
    assert r.ok, r.note()
    picked = select_certified_plays([lane, pro], signals=payload, sport="ncaaf")
    assert len(picked) == 1 and picked[0]["pro_confirmed"]
    assert picked[0]["units"] == 1.5


def test_pro_tier_rejects_price_worse_than_vig():
    board = _board()
    pro = build_pro_tier_candidates([_event(fd_over=-135)], [board], sport="ncaaf")[0]
    r = evaluate_product_play(pro, signals={"signals": [pro], "split_boards": [board]}, sport="ncaaf")
    assert not r.ok and "worse than no-vig fair" in r.note()


def test_pro_tier_drops_when_signal_leaves_board():
    pro = build_pro_tier_candidates([_event()], [_board()], sport="ncaaf")[0]
    gone = _board(signals=(SHARP,))
    r = evaluate_product_play(pro, signals={"signals": [pro], "split_boards": [gone]}, sport="ncaaf")
    assert not r.ok and "model" in r.note()


def test_pro_rows_excluded_from_duplicate_p_true():
    rows = [
        {"event_id": f"e{i}", "market": "totals", "side": "over", "line": 50.5, "p_true": 0.54, "pro_confirmed": True}
        for i in range(6)
    ]
    assert _duplicate_p_true_clusters({"signals": rows}) == set()


def _lane_spread(**kw):
    base = {
        "filter_passed": True,
        "event_id": "e1",
        "home_team": "ALA",
        "away_team": "UGA",
        "market": "spreads",
        "side": "home",
        "line": -3.5,
        "book": "fanduel",
        "tier": "play",
        "edge": 0.05,
        "p_fair": 0.55,
        "p_mkt": 0.55,
        "sharp_book": "pinnacle",
        "price": -110,
        "flags": {"money_split": True},
    }
    base.update(kw)
    return base


def test_public_side_veto_on_spreads():
    play = _lane_spread(home_team="KC", away_team="LAC")
    board = _board(market="spread", side="home", tickets=0.72, home="KC", away="LAC")
    r = evaluate_product_play(play, signals={"signals": [play], "split_boards": [board]}, sport="nfl")
    assert not r.ok and "public side" in r.note()
    ok_board = _board(market="spread", side="home", tickets=0.40, home="KC", away="LAC")
    r = evaluate_product_play(play, signals={"signals": [play], "split_boards": [ok_board]}, sport="nfl")
    assert r.ok, r.note()


def test_non_bettable_book_rejected():
    play = _lane_spread(book="draftkings", home_team="KC", away_team="LAC")
    r = evaluate_product_play(play, signals=None, sport="nfl")
    assert not r.ok and "not bettable" in r.note()


def test_nfl_price_only_needs_ev_vs_fair():
    # -110 needs p_fair > 0.534 for +2% EV against the no-vig fair.
    thin = _lane_spread(p_fair=0.52, p_mkt=0.52, home_team="KC", away_team="LAC")
    r = evaluate_product_play(thin, signals=None, sport="nfl")
    assert not r.ok and "price-only" in r.note()
    fat = _lane_spread(p_fair=0.55, p_mkt=0.55, home_team="KC", away_team="LAC")
    assert evaluate_product_play(fat, signals=None, sport="nfl").ok


def test_ncaaf_totals_lane_half_units():
    play = {**_lane_spread(), "market": "totals", "side": "over", "line": 52.5, "edge": 0.06}
    picked = select_certified_plays([play], signals={"signals": [play], "split_boards": []}, sport="ncaaf")
    assert picked and picked[0]["units"] == 0.75
