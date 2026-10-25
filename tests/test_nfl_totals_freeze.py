"""Kickoff freeze for NFL totals board rows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.nfl.totals.tracker import load_totals_board, save_totals_board, upsert_totals_rows


def test_freeze_pregame_projection_at_kickoff(tmp_path, monkeypatch):
    path = tmp_path / "nfl_game_totals.json"
    save_totals_board({"games": []}, path=path)
    kick = datetime.now(timezone.utc) - timedelta(hours=2)
    kick_s = kick.isoformat()
    upsert_totals_rows(
        [
            {
                "event_id": "ev1",
                "away_team": "SF",
                "home_team": "LAR",
                "kickoff": kick_s,
                "projection_total": 44.0,
                "sim_median": 43.5,
                "market_line": 48.0,
                "sim_lean": "under",
            }
        ],
        path=path,
        now=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    upsert_totals_rows(
        [
            {
                "event_id": "ev1",
                "away_team": "SF",
                "home_team": "LAR",
                "kickoff": kick_s,
                "projection_total": 25.5,
                "sim_median": 25.5,
                "market_line": 69.5,
                "sim_lean": "under",
            }
        ],
        path=path,
        now=datetime.now(timezone.utc),
    )
    board = load_totals_board(path)
    row = board["games"][0]
    assert row["frozen"] is True
    assert row["projection_total"] == 44.0
    assert row["market_line"] == 48.0
