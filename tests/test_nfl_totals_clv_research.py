"""Smoke tests for NFL totals CLV research helpers."""

from __future__ import annotations

from sharp_scout.nfl.totals.clv_research import (
    _grade,
    build_scan_rows,
    coverage_report,
    run_signal_backtests,
)
from sharp_scout.data.line_store import load_history


def test_grade_totals():
    assert _grade("over", 45.0, 50.0) == "W"
    assert _grade("under", 45.0, 50.0) == "L"


def test_coverage_and_signals_smoke():
    hist = load_history()
    rows = build_scan_rows(history=hist)
    cov = coverage_report(history=hist, scan_rows=rows)
    assert cov["completed_nfl_games_2026"] >= 90
    if rows:
        res = run_signal_backtests(rows[:50])
        assert "pinnacle_momentum_follow" in res
