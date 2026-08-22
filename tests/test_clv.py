"""Closing Line Value tests."""

from __future__ import annotations

from sharp_scout.ledger.clv import (
    clv_points,
    clv_prob,
    finalize_closing_lines,
    summarize_clv,
)


def test_clv_points_spread_beat_close():
    # Bet home -2.5, closed -4.0 → we got 1.5 points of value.
    assert clv_points("spreads", "home", -2.5, -4.0) == 1.5
    # Bet home -4.0, closed -2.5 → negative CLV.
    assert clv_points("spreads", "home", -4.0, -2.5) == -1.5


def test_clv_points_totals():
    # Over 47.5 closing at 49.5 → market moved to over, we bought the lower number.
    assert clv_points("totals", "over", 47.5, 49.5) == 2.0
    # Under 47.5 closing 45.5 → favorable for under.
    assert clv_points("totals", "under", 47.5, 45.5) == 2.0


def test_clv_prob_positive_when_price_shortens():
    # Bet +120 (implied ~0.4545), closed -110 (implied ~0.5238) → positive CLV prob.
    v = clv_prob(120, -110)
    assert v is not None and v > 0


def test_finalize_and_summary_with_history():
    ledger = {
        "plays": [
            {
                "event_id": "e1",
                "market": "spreads",
                "side": "away",
                "line": -2.5,
                "price": -110,
                "kickoff": "2026-09-10T00:00:00+00:00",
                "clv_at": None,
            }
        ]
    }
    history = {
        "e1|spreads|away": [
            {"ts": "2026-09-09T18:00:00+00:00", "book": "pinnacle", "line": -2.5, "price": -110},
            {"ts": "2026-09-09T23:30:00+00:00", "book": "pinnacle", "line": -4.0, "price": -108},
        ]
    }
    updated = finalize_closing_lines(ledger, history=history)
    assert updated == 1
    play = ledger["plays"][0]
    assert play["close_line"] == -4.0
    assert play["clv_points"] == 1.5  # -2.5 - (-4.0)
    summary = summarize_clv(ledger)
    assert summary["n_plays_with_clv"] == 1
    assert summary["avg_clv_points"] == 1.5
