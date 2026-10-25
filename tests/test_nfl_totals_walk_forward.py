"""Walk-forward backtest helpers."""

from __future__ import annotations

from sharp_scout.nfl.totals.walk_forward import (
    GameInput,
    _grade,
    _units,
    run_walk_forward_backtest,
)
import pandas as pd


def test_grade_and_units():
    assert _grade("over", 45.0, 50.0) == "W"
    assert _grade("under", 45.0, 50.0) == "L"
    assert _grade("over", 45.0, 45.0) == "P"
    assert _units("W", -110) > 0.9
    assert _units("L", -110) == -1.0


def test_walk_forward_runs_on_tiny_slate():
    games = [
        GameInput(
            season=2026,
            week=2,
            kickoff_et="2026-09-20 13:00",
            away="KC",
            home="BUF",
            final_total=44.0,
            close_line=47.5,
            close_price=-110,
            scan_line=47.5,
            scan_price=-110,
            old_model_total=45.0,
            old_pick="under",
            old_result_close="W",
            old_units_110=0.91,
            old_units_close=0.91,
        )
    ]
    rows, summary = run_walk_forward_backtest(games, pbp=pd.DataFrame(), n_sims=500)
    assert len(rows) == 1
    assert summary["n_games"] == 1
    assert "sim_only" in summary
