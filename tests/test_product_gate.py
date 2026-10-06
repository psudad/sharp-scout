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


def _total_split(over_tix, over_money, under_tix, under_money):
    def _row(label, t, m):
        return {"label": label, "tickets_pct": t, "money_pct": m, "diff_pct": round(m - t, 4)}

    sides = {
        "over": _row("Over", over_tix, over_money),
        "under": _row("Under", under_tix, under_money),
    }
    best_side, best_diff = None, 0.0
    for s, r in sides.items():
        if r["diff_pct"] > best_diff:
            best_side, best_diff = s, r["diff_pct"]
    edge = (
        {"available": True, "side": best_side, "team": sides[best_side]["label"], "diff_pct": best_diff}
        if best_side
        else {"available": False, "side": None, "team": None, "diff_pct": None}
    )
    return {
        "home_team": "SEA",
        "away_team": "LAC",
        "available": True,
        "markets": {"total": {"sides": sides, "sharp_edge": edge}},
    }


def _total_play(**kw):
    base = dict(
        market="totals",
        side="under",
        line=43.0,
        home_team="SEA",
        away_team="LAC",
        event_id="e2",
        edge=0.07,
        p_fair=0.52,
        p_mkt=0.52,
        model_total=39.4,
    )
    base.update(kw)
    return _sig(**base)


def test_total_vetoed_when_both_tickets_and_handle_oppose():
    # SEA U43: over 54%/54%, under 46%/46% — crowd AND money on the over.
    signals = {
        "signals": [_total_play(book="dk"), _total_play(book="coolbet")],
        "split_boards": [_total_split(0.54, 0.54, 0.46, 0.46)],
    }
    r = evaluate_product_play(_total_play(), signals=signals, sport="nfl")
    assert not r.ok and "favor over" in r.note()


def test_total_vetoed_when_sharp_money_opposes():
    # NO U48: over 37% tix / 45% money (+8% sharp on over) and model 6.4 pts off market.
    signals = {
        "signals": [
            _total_play(line=48.0, model_total=41.6, book="dk"),
            _total_play(line=48.0, model_total=41.6, book="lowvig"),
        ],
        "split_boards": [_total_split(0.37, 0.45, 0.63, 0.55)],
    }
    r = evaluate_product_play(
        _total_play(line=48.0, model_total=41.6), signals=signals, sport="nfl"
    )
    assert not r.ok
    assert "opposes our under" in r.note() or "without sharp-money confirmation" in r.note()


def test_total_passes_when_money_confirms_our_side():
    # Under gets the sharp money (+12%) and model is close to the line — this should certify.
    signals = {
        "signals": [_total_play(book="dk"), _total_play(book="pinnacle")],
        "split_boards": [_total_split(0.55, 0.43, 0.45, 0.57)],
    }
    r = evaluate_product_play(_total_play(), signals=signals, sport="nfl")
    assert r.ok, r.note()


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
