"""Tests for plain-English copy and signal deduplication."""

from __future__ import annotations

from sharp_scout.copy.explain import (
    collapse_best_signals,
    format_kickoff_et,
    format_play_rationale,
)


def test_collapse_best_signals_one_per_side():
    signals = [
        {"event_id": "e1", "market": "spreads", "side": "home", "line": 2.5, "book": "dk", "edge": 0.05},
        {"event_id": "e1", "market": "spreads", "side": "home", "line": 2.5, "book": "fd", "edge": 0.08},
        {"event_id": "e1", "market": "spreads", "side": "away", "line": -2.5, "book": "dk", "edge": 0.03},
    ]
    out = collapse_best_signals(signals)
    assert len(out) == 2
    assert out[0]["book"] == "fd"
    assert out[0]["edge"] == 0.08


def test_format_kickoff_et():
    assert "ET" in format_kickoff_et("2026-08-15T17:00:00+00:00")


def test_format_play_rationale_includes_edge():
    play = {
        "market": "spreads",
        "side": "home",
        "home_team": "NYG",
        "away_team": "MIN",
        "line": 1.5,
        "book": "draftkings",
        "price": -105,
        "p_true": 0.64,
        "p_mkt": 0.52,
        "edge": 0.12,
        "flags": {"money_split": True},
        "filter_notes": ["money-ticket gap +22% on home (money=58% tickets=36%)"],
    }
    text = format_play_rationale(play)
    assert "12.0%" in text or "12%" in text
    assert "NYG" in text
