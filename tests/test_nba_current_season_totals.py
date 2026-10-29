"""Current-season-only totals (no prior-year blend on total path)."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.nba.score_model.current_season_totals import (
    project_total_current_season,
    project_total_legacy_prior_blend,
)
from sharp_scout.nba.score_model.engine import HistRow, V2Engine, V2Params, TeamPrior


def _row(*, home: str, away: str, dt: datetime, pace: float, h_ortg: float, a_ortg: float) -> HistRow:
    return HistRow(
        date=dt,
        home=home,
        away=away,
        home_ortg=h_ortg,
        away_ortg=a_ortg,
        pace=pace,
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


def test_current_season_total_ignores_prior_season_history():
    engine = V2Engine(params=V2Params(), stage=3)
    engine.season_priors["DEN"] = TeamPrior(off=118.0, def_=110.0, pace=102.0)
    engine.season_priors["NOP"] = TeamPrior(off=115.0, def_=112.0, pace=101.0)
    engine.team_games.update({"DEN": 3, "NOP": 3})
    # Old-season high-scoring games (would inflate legacy total via priors + observe)
    engine.history.append(
        _row(
            home="DEN",
            away="NOP",
            dt=datetime(2025, 3, 1, tzinfo=timezone.utc),
            pace=105.0,
            h_ortg=120.0,
            a_ortg=118.0,
        )
    )
    # Current season: slow games only
    engine.history.append(
        _row(
            home="DEN",
            away="NOP",
            dt=datetime(2026, 10, 20, tzinfo=timezone.utc),
            pace=95.0,
            h_ortg=105.0,
            a_ortg=104.0,
        )
    )
    engine.history.append(
        _row(
            home="NOP",
            away="DEN",
            dt=datetime(2026, 10, 22, tzinfo=timezone.utc),
            pace=94.0,
            h_ortg=106.0,
            a_ortg=103.0,
        )
    )
    kick = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
    cs = project_total_current_season(engine, "NOP", "DEN", game_date=kick)
    legacy = project_total_legacy_prior_blend(engine, "NOP", "DEN", game_date=kick)
    assert cs["total"] < legacy - 5.0
    assert cs["total_diagnostics"]["home"]["games"] >= 1
    assert cs["total_diagnostics"]["away"]["games"] >= 1


def test_engine_project_total_uses_current_season_path():
    engine = V2Engine(params=V2Params(), stage=3)
    engine.season_priors["MIN"] = TeamPrior(off=120.0, def_=108.0, pace=102.0)
    engine.season_priors["GSW"] = TeamPrior(off=118.0, def_=110.0, pace=100.0)
    engine.team_games.update({"MIN": 2, "GSW": 2})
    engine.history.append(
        _row(
            home="MIN",
            away="GSW",
            dt=datetime(2026, 10, 24, tzinfo=timezone.utc),
            pace=98.0,
            h_ortg=108.0,
            a_ortg=107.0,
        )
    )
    kick = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
    p = engine.project("MIN", "GSW", game_date=kick)
    assert "total_diagnostics" in p
    assert p["total"] == project_total_current_season(engine, "MIN", "GSW", game_date=kick)["total"]
    assert p["total_home_pts"] + p["total_away_pts"] == p["total"]
