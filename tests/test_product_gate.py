"""Product gate — sellable / LOCKED card eligibility."""

from __future__ import annotations

from sharp_scout.qa.product_gate import evaluate_product_play, select_certified_plays


def _sig(**kw):
    base = {
        "filter_passed": True,
        "event_id": "e1",
        "market": "spreads",
        "side": "away",
        "line": 7.5,
        "book": "draftkings",
        "tier": "play",
        "edge": 0.05,
        "p_fair": 0.52,
        "p_mkt": 0.52,
    }
    base.update(kw)
    return base


def _split_board_for(side: str = "away", spread_gap: float = 0.12, ml_gap: float = 0.12):
    return {
        "home_team": "LV",
        "away_team": "MIA",
        "available": True,
        "markets": {
            "spread": {
                "sharp_edge": {
                    "available": True,
                    "side": side,
                    "team": "MIA" if side == "away" else "LV",
                    "diff_pct": spread_gap,
                }
            },
            "moneyline": {
                "sharp_edge": {
                    "available": True,
                    "side": side,
                    "team": "MIA" if side == "away" else "LV",
                    "diff_pct": ml_gap,
                }
            },
        },
    }


def test_ml_requires_split_board_confirmation():
    play = _sig(
        market="h2h",
        side="away",
        line=None,
        home_team="LV",
        away_team="MIA",
        edge=0.06,
        p_fair=0.52,
    )
    signals = {
        "signals": [
            _sig(market="h2h", side="away", line=None, book="draftkings"),
            _sig(market="h2h", side="away", line=None, book="fanduel"),
        ],
    }
    r = evaluate_product_play(play, signals=signals, sport="nfl")
    assert not r.ok and "split-board" in r.note()

    signals["split_boards"] = [_split_board_for(side="away")]
    r2 = evaluate_product_play(play, signals=signals, sport="nfl")
    assert r2.ok

    signals["split_boards"] = [_split_board_for(side="home", spread_gap=0.12, ml_gap=0.12)]
    r3 = evaluate_product_play(play, signals=signals, sport="nfl")
    assert not r3.ok and "conflicts" in r3.note()


def test_rejects_lean_tier():
    signals = {"signals": [_sig(), _sig(book="fanduel")]}
    r2 = evaluate_product_play(_sig(tier="lean"), signals=signals, sport="nfl")
    assert not r2.ok and "tier" in r2.note()


def test_requires_p_fair_and_ev():
    signals = {"signals": [_sig(), _sig(book="fanduel")]}
    r = evaluate_product_play(_sig(p_fair=0.48, p_mkt=0.48), signals=signals, sport="ncaaf")
    assert not r.ok

    r2 = evaluate_product_play(_sig(edge=0.02), signals=signals, sport="ncaaf")
    assert not r2.ok


def test_select_certified_caps_and_dedupes():
    signals = {
        "signals": [
            _sig(edge=0.06, book="dk"),
            _sig(edge=0.05, book="fd"),
            _sig(edge=0.08, event_id="e2", market="totals", side="over", line=45.5, book="dk"),
            _sig(edge=0.07, event_id="e2", market="totals", side="over", line=45.5, book="pin"),
        ]
    }
    cands = signals["signals"]
    out = select_certified_plays(cands, signals=signals, sport="nfl")
    assert len(out) <= 5
    assert out[0]["edge"] == 0.08
    keys = {(x["event_id"], x["market"]) for x in out}
    assert len(keys) == len(out)
