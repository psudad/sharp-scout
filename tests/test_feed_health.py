from __future__ import annotations

from sharp_scout.health.feeds import FeedHealthRegistry, FeedStatus, write_feeds_file
from sharp_scout.phase4.filters import _find_split_game


def test_find_split_game_matches_swapped_home_labels(tmp_path):
    splits = [{"home_team": "BUF", "away_team": "KC", "markets": {"spread": {"home_bet_pct": 0.5}}}]
    assert _find_split_game(splits, "KC", "BUF", sport="nfl") is not None


def test_write_feeds_file(tmp_path, monkeypatch):
    path = tmp_path / "feeds.json"
    monkeypatch.setattr("sharp_scout.health.feeds.FEEDS_PATH", path)
    reg = FeedHealthRegistry()
    reg.update("odds_api_nfl", status=FeedStatus.OK, reason="test", last_success_at="2026-01-01T00:00:00+00:00")
    write_feeds_file(reg, context="test")
    assert path.exists()
    data = path.read_text()
    assert "odds_api_nfl" in data