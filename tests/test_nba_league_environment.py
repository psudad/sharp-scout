"""League efficiency re-centering (walk-forward, flag-gated)."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.nba.score_model.engine import HistRow, V2Engine, V2Params
from sharp_scout.nba.score_model.league_environment import efficiency_scale, rolling_league_ortg


def test_rolling_league_ortg_no_lookahead():
    engine = V2Engine(params=V2Params(), stage=3)
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 2, tzinfo=timezone.utc)
    engine.history.append(
        HistRow(
            date=t0,
            home="BOS",
            away="NYK",
            home_ortg=118.0,
            away_ortg=106.0,
            pace=100.0,
            home_rest=2,
            away_rest=2,
            home_b2b=0,
            away_b2b=0,
            home_3in4=0,
            away_3in4=0,
            home_travel=0,
            away_travel=0,
            home_alt=0,
            away_alt=0,
            weight=1.0,
        )
    )
    assert rolling_league_ortg(engine, before=t1, min_games=1) == 112.0
    assert rolling_league_ortg(engine, before=t0, min_games=1) is None


def test_efficiency_scale_force_without_live_flag(monkeypatch):
    from sharp_scout.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "nba_league_efficiency_correction_enabled", False)
    engine = V2Engine(params=V2Params(), stage=3)
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 2, tzinfo=timezone.utc)
    engine.history.append(
        HistRow(
            date=t0,
            home="BOS",
            away="NYK",
            home_ortg=112.0,
            away_ortg=112.0,
            pace=100.0,
            home_rest=2,
            away_rest=2,
            home_b2b=0,
            away_b2b=0,
            home_3in4=0,
            away_3in4=0,
            home_travel=0,
            away_travel=0,
            home_alt=0,
            away_alt=0,
            weight=1.0,
        )
    )
    assert efficiency_scale(engine, t1, force=True, min_games=1) == 1.0
    assert efficiency_scale(engine, t1, force=False) is None
