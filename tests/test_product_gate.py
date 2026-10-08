"""Product gate — sellable / LOCKED card eligibility."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.qa.product_gate import (
    evaluate_product_play,
    is_shadow_only,
    select_certified_plays,
    select_shadow_plays,
)


def _sig(**kw):
    base = {
        "filter_passed": True,
        "event_id": "e1",
        "home_team": "LV",
        "away_team": "MIA",
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


def _spread_split(
    side: str = "away",
    gap: float = 0.12,
    *,
    home_team: str = "LV",
    away_team: str = "MIA",
):
    team = away_team if side == "away" else home_team
    return {
        "home_team": home_team,
        "away_team": away_team,
        "available": True,
        "markets": {
            "spread": {
                "sharp_edge": {
                    "available": True,
                    "side": side,
                    "team": team,
                    "diff_pct": gap,
                }
            }
        },
    }


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
    assert not r2.ok and is_shadow_only(r2.reasons)

    signals["split_boards"] = [_split_board_for(side="home", spread_gap=0.12, ml_gap=0.12)]
    r3 = evaluate_product_play(play, signals=signals, sport="nfl")
    assert not r3.ok and "conflicts" in r3.note()


def test_rejects_lean_tier():
    signals = {"signals": [_sig(), _sig(book="fanduel")]}
    r2 = evaluate_product_play(_sig(tier="lean"), signals=signals, sport="nfl")
    assert not r2.ok and "tier" in r2.note()


def _spread_signals(**sig_kw):
    play = _sig(**sig_kw)
    home, away = play["home_team"], play["away_team"]
    side = play.get("side", "away")
    return {
        "signals": [play, _sig(book="fanduel", **{k: v for k, v in sig_kw.items() if k != "book"})],
        "split_boards": [_spread_split(side=side, home_team=home, away_team=away)],
    }


def test_requires_p_fair_and_ev():
    signals = _spread_signals()
    r = evaluate_product_play(_sig(p_fair=0.48, p_mkt=0.48), signals=signals, sport="ncaaf")
    assert not r.ok

    r2 = evaluate_product_play(_sig(edge=0.02), signals=signals, sport="ncaaf")
    assert not r2.ok


def test_rejects_price_worse_than_sharp_fair():
    signals = _spread_signals()
    ok = evaluate_product_play(_sig(price=-110), signals=signals, sport="nfl")
    assert ok.ok, ok.note()

    # Fair 52% vs -125 (55.6% implied): we'd be paying 3.6% over sharp — negative CLV at entry.
    bad = evaluate_product_play(_sig(price=-125), signals=signals, sport="nfl")
    assert not bad.ok and "worse than sharp fair" in bad.note()


def test_ml_shadow_plays_selected_for_watchlist_not_certified():
    ml = dict(market="h2h", side="away", line=None, home_team="LV", away_team="MIA")
    signals = {
        "signals": [_sig(**ml, book="dk"), _sig(**ml, book="fd", edge=0.06)],
        "split_boards": [_split_board_for(side="away")],
    }
    cands = signals["signals"]
    assert select_certified_plays(cands, signals=signals, sport="nfl") == []
    shadow = select_shadow_plays(cands, signals=signals, sport="nfl")
    assert len(shadow) == 1 and shadow[0]["product_shadow"] is True
    assert shadow[0]["edge"] == 0.06


def test_ml_with_other_failures_is_not_shadowed():
    ml = dict(market="h2h", side="away", line=None, home_team="LV", away_team="MIA")
    signals = {"signals": [_sig(**ml, book="dk"), _sig(**ml, book="fd")]}
    # No split board: fails on confirmation, not just shadow — stays out of the watchlist.
    assert select_shadow_plays(signals["signals"], signals=signals, sport="nfl") == []


def test_append_signals_watchlist_status(tmp_path):
    from sharp_scout.ledger.tracker import append_signals, load_ledger

    path = tmp_path / "ledger.json"
    play = _sig(market="h2h", side="away", line=None, price=120, commence_time="2099-01-01T00:00:00Z")
    append_signals([play], path=path, status="watchlist")
    rows = load_ledger(path)["plays"]
    assert len(rows) == 1 and rows[0]["status"] == "watchlist"


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


def test_spread_vetoed_when_sharp_money_gap_below_bar():
    signals = _spread_signals(edge=0.08)
    signals["split_boards"] = [_spread_split(side="away", gap=0.08)]
    play = _sig(
        edge=0.08,
        kickoff="2099-06-01T20:00:00+00:00",
        commence_time="2099-06-01T20:00:00+00:00",
    )
    r = evaluate_product_play(play, signals=signals, sport="nfl")
    assert not r.ok and "spread money-ticket gap" in r.note()


def test_spread_blocked_inside_lead_window():
    now = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    kick = (now + timedelta(hours=4)).isoformat()
    signals = _spread_signals()
    play = _sig(kickoff=kick, commence_time=kick)
    r = evaluate_product_play(play, signals=signals, sport="nfl", now=now)
    assert not r.ok and "until kickoff" in r.note()


def test_southern_miss_style_spread_would_not_certify_at_post_time():
    """Replay USM +10 @ TROY: +8% spread sharp money and T-4h — both guardrails fire."""
    post_time = datetime(2026, 10, 6, 20, 4, 35, tzinfo=timezone.utc)
    kick = "2026-10-07T00:00:00+00:00"
    play = _sig(
        event_id="57ad14afc7db1843fd56f5971dadb058",
        home_team="TROY",
        away_team="SOUTHERN MISS",
        side="away",
        line=10.0,
        edge=0.1367,
        price=-104,
        kickoff=kick,
        commence_time=kick,
    )
    signals = {
        "signals": [play, _sig(book="pinnacle", event_id=play["event_id"], home_team="TROY", away_team="SOUTHERN MISS")],
        "split_boards": [
            _spread_split(side="away", gap=0.08, home_team="TROY", away_team="SOUTHERN MISS")
        ],
    }
    r = evaluate_product_play(play, signals=signals, sport="ncaaf", now=post_time)
    assert not r.ok
    assert "spread money-ticket gap" in r.note() or "until kickoff" in r.note()


def test_select_certified_caps_and_dedupes():
    signals = {
        "signals": [
            _sig(edge=0.06, book="dk"),
            _sig(edge=0.05, book="fd"),
            _sig(edge=0.08, event_id="e2", market="totals", side="over", line=45.5, book="dk"),
            _sig(edge=0.07, event_id="e2", market="totals", side="over", line=45.5, book="pin"),
        ],
        "split_boards": [_spread_split()],
    }
    cands = signals["signals"]
    out = select_certified_plays(cands, signals=signals, sport="nfl")
    assert len(out) <= 5
    assert out[0]["edge"] == 0.08
    keys = {(x["event_id"], x["market"]) for x in out}
    assert len(keys) == len(out)
