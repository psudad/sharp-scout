"""Tests for plain-English copy and signal deduplication."""

from __future__ import annotations

from sharp_scout.copy.explain import (
    STAGE_RECORD_TIPS,
    collapse_best_signals,
    format_kickoff_et,
    format_play_rationale,
)


def test_stage_record_tips_cover_all_lenses():
    for stage in ("hybrid", "model", "sharp", "public", "money", "sharp_edge", "rlm"):
        assert stage in STAGE_RECORD_TIPS
        assert len(STAGE_RECORD_TIPS[stage]) > 20


def test_collapse_best_signals_one_per_side():
    signals = [
        {"event_id": "e1", "market": "spreads", "side": "home", "line": 1.5, "book": "dk", "edge": 0.05},
        {"event_id": "e1", "market": "spreads", "side": "home", "line": 2.5, "book": "fd", "edge": 0.08},
        {"event_id": "e1", "market": "spreads", "side": "away", "line": -2.5, "book": "dk", "edge": 0.03},
    ]
    out = collapse_best_signals(signals)
    assert len(out) == 2
    home = next(s for s in out if s["side"] == "home")
    assert home["book"] == "fd"
    assert home["line"] == 2.5
    assert home["edge"] == 0.08


def test_format_kickoff_et():
    text = format_kickoff_et("2026-08-15T17:00:00+00:00")
    assert "ET" in text
    assert "Aug" in text
    assert "Sat" in text or "Fri" in text  # depends on ET offset
    assert ":" in text

    from sharp_scout.copy.explain import format_kickoff_compact

    compact = format_kickoff_compact("2026-09-10T00:15:00Z")
    assert "Sep" in compact
    assert "Wed" in compact
    assert "8:15" in compact
    assert "ET" in compact


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
