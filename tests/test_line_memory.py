"""Tests for opening line memory."""

from __future__ import annotations

from pathlib import Path

from sharp_scout.data import line_memory as lm


def test_overlay_open_lines_stores_first_seen(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lm, "OPEN_LINES_PATH", tmp_path / "open_lines.json")
    games = [
        {
            "game_id": "123",
            "markets": {
                "spread": {"current_line": 2.5},
                "total": {"current_line": 41.5},
            },
        }
    ]
    out = lm.overlay_open_lines(games)
    assert out[0]["markets"]["spread"]["open_line"] == 2.5
    games[0]["markets"]["spread"]["current_line"] = 3.0
    out2 = lm.overlay_open_lines(games)
    assert out2[0]["markets"]["spread"]["open_line"] == 2.5
