"""Demo KC@BUF must not persist on live totals board."""

from __future__ import annotations

from pathlib import Path

from sharp_scout.data.odds_api import DEMO_NFL_EVENT_ID, mock_odds_events
from sharp_scout.nfl.totals.tracker import load_totals_board, purge_demo_games, upsert_totals_rows


def test_upsert_excludes_demo_without_flag(tmp_path: Path, monkeypatch):
    board_path = tmp_path / "nfl_game_totals.json"
    monkeypatch.setattr(
        "sharp_scout.nfl.totals.tracker.DEFAULT_PATH",
        board_path,
    )
    ev = mock_odds_events()[0]
    upsert_totals_rows(
        [
            {
                "event_id": ev["event_id"],
                "home_team": "BUF",
                "away_team": "KC",
                "sim_median": 47.0,
                "market_line": 47.5,
            }
        ],
        path=board_path,
        allow_demo_events=False,
    )
    board = load_totals_board(board_path)
    assert all(g.get("event_id") != DEMO_NFL_EVENT_ID for g in board["games"])


def test_purge_removes_existing_demo(tmp_path: Path, monkeypatch):
    board_path = tmp_path / "nfl_game_totals.json"
    monkeypatch.setattr("sharp_scout.nfl.totals.tracker.DEFAULT_PATH", board_path)
    board_path.write_text(
        '{"games":[{"event_id":"demo-kc-buf","away_team":"KC","home_team":"BUF"}],'
        '"updated_at":null}\n'
    )
    n = purge_demo_games(path=board_path)
    assert n == 1
    assert load_totals_board(board_path)["games"] == []
