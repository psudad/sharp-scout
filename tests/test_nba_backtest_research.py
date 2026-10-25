"""Offline tests for NBA research backtest (no network)."""

from __future__ import annotations

from sharp_scout.research.nba_paper_backtest import run_game_line_backtest, yahoo_row_to_event


def _sample_row() -> dict:
    return {
        "_season": "2024-25",
        "game_id": "nba.g.test",
        "game_date": "2024-10-22-10:00",
        "away_team": "New York",
        "home_team": "Boston",
        "total_over_points": 221.5,
        "total_over_odds": -110,
        "total_over_won": True,
        "total_under_points": 221.5,
        "total_under_odds": -110,
        "total_under_won": False,
        "money_away_odds": 195,
        "money_away_won": False,
        "money_home_odds": -250,
        "money_home_won": True,
        "spread_away_points": 5.5,
        "spread_away_odds": -105,
        "spread_away_won": False,
        "spread_home_points": -5.5,
        "spread_home_odds": -115,
        "spread_home_won": True,
    }


def test_yahoo_row_builds_event():
    ev = yahoo_row_to_event(_sample_row())
    assert ev is not None
    assert ev["away_team"] == "NYK"
    assert "pinnacle" in ev["bookmakers"]
    assert "fanduel" in ev["bookmakers"]


def test_backtest_emits_graded_rows():
    result = run_game_line_backtest([_sample_row()], score_index={})
    assert result.bets
    gates = {b.gate for b in result.bets}
    assert "every_game" in gates
