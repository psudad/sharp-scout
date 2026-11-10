"""v1 Pace market blend toward consensus total (flag off by default)."""

from __future__ import annotations

from sharp_scout.nba.score_model.pace_v1 import blend_total_toward_market


def test_blend_off_by_default():
    assert blend_total_toward_market(230.0, 220.0) == 230.0


def test_blend_when_enabled(monkeypatch):
    from sharp_scout.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "nba_pace_v1_market_blend_enabled", True)
    monkeypatch.setattr(s, "nba_pace_v1_market_blend_model_weight", 0.5)
    assert blend_total_toward_market(230.0, 220.0) == 225.0
