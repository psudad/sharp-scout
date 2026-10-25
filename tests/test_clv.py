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


def test_clv_prob_skipped_when_line_differs():
    play = {
        "market": "totals",
        "side": "over",
        "line": 39.5,
        "price": -110,
    }
    from sharp_scout.ledger.clv import compute_clv_for_play

    compute_clv_for_play(play, 51.5, -110, close_book="pinnacle", at="2026-10-24T23:00:00+00:00")
    assert play["clv_points"] == 12.0
    assert play["clv_prob"] is None
    assert play["clv_basis"] == "points"


def test_finalize_refreshes_before_kickoff_then_freezes():
    from datetime import datetime, timezone

    from sharp_scout.ledger.clv import finalize_closing_lines

    ledger = {
        "plays": [
            {
                "event_id": "e1",
                "market": "spreads",
                "side": "away",
                "line": -2.5,
                "price": -110,
                "kickoff": "2026-09-10T00:00:00+00:00",
                "clv_at": "2026-09-09T18:00:00+00:00",
                "close_line": -2.5,
                "close_price": -110,
                "close_book": "pinnacle",
            }
        ]
    }
    history = {
        "e1|spreads|away": [
            {"ts": "2026-09-09T18:00:00+00:00", "book": "pinnacle", "line": -2.5, "price": -110},
            {"ts": "2026-09-09T23:30:00+00:00", "book": "pinnacle", "line": -4.0, "price": -108},
        ]
    }
    now = datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)
    assert finalize_closing_lines(ledger, history=history, now=now) == 1
    assert ledger["plays"][0]["close_line"] == -4.0
    assert finalize_closing_lines(ledger, history=history, now=now) == 0


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
