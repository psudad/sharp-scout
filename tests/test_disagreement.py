"""Model-vs-market disagreement classifier tests."""

from __future__ import annotations

from sharp_scout.analysis.disagreement import (
    build_disagreements,
    classify_disagreement,
    summarize_disagreements,
)


def test_classify_public_bias_from_rlm():
    play = {"p_true": 0.60, "p_mkt": 0.52, "flags": {"rlm": True}}
    result = classify_disagreement(play)
    assert result["category"] == "public_bias"


def test_classify_weather():
    play = {"p_true": 0.60, "p_mkt": 0.52, "wind": 22, "flags": {}}
    result = classify_disagreement(play)
    assert result["category"] == "weather"


def test_build_disagreements_respects_threshold():
    signals = [
        {"event_id": "e1", "market": "spreads", "side": "home", "p_true": 0.60, "p_mkt": 0.52, "flags": {"rlm": True}},
        {"event_id": "e2", "market": "totals", "side": "over", "p_true": 0.51, "p_mkt": 0.50, "flags": {}},
    ]
    recs = build_disagreements(signals, threshold=0.05, season=2026, week=1)
    assert len(recs) == 1
    assert recs[0]["event_id"] == "e1"


def test_summary_counts_and_hit_rate():
    recs = [
        {"category": "public_bias", "outcome": "win"},
        {"category": "public_bias", "outcome": "loss"},
        {"category": "weather", "outcome": None},
    ]
    summary = summarize_disagreements(recs)
    assert summary["n"] == 3
    assert summary["by_category"]["public_bias"]["count"] == 2
    assert summary["by_category"]["public_bias"]["win_pct"] == 0.5
