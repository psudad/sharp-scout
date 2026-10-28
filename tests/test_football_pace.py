"""Shadow football pace model — offline unit tests."""

from __future__ import annotations

from sharp_scout.football_pace.backtest import summarize_graded, walk_forward_backtest
from sharp_scout.football_pace.config import NFL_PACE_CONFIG
from sharp_scout.football_pace.engine import PaceEngine
from sharp_scout.football_pace.games import PaceGame
from sharp_scout.football_pace.lines import grade_ats, grade_total, nflverse_home_spread


def test_nflverse_spread_sign_flip():
    assert nflverse_home_spread(6.5) == -6.5


def test_grade_ats_respects_min_edge():
    assert grade_ats(7.0, -3.5, proj_margin=2.0, min_edge=3.0) is None
    assert grade_ats(10.0, -3.5, proj_margin=7.0, min_edge=3.0) == "win"


def test_grade_total_under():
    assert grade_total(41.0, 44.5, proj_total=40.0, min_edge=3.0) == "win"


def test_walk_forward_two_games():
    cfg = NFL_PACE_CONFIG
    games = [
        PaceGame(
            sport="nfl",
            season=2024,
            week=1,
            game_id="g1",
            game_date=None,
            home="KC",
            away="BAL",
            home_score=27.0,
            away_score=20.0,
            spread_home=-3.0,
            total_line=48.0,
            home_plays=65.0,
            away_plays=62.0,
        ),
        PaceGame(
            sport="nfl",
            season=2024,
            week=2,
            game_id="g2",
            game_date=None,
            home="BUF",
            away="MIA",
            home_score=31.0,
            away_score=24.0,
            spread_home=-2.5,
            total_line=50.0,
            home_plays=68.0,
            away_plays=60.0,
        ),
    ]
    rows, engine = walk_forward_backtest(games, cfg)
    assert len(rows) == 2
    assert engine.team_games.get("KC") == 1
    summary = summarize_graded(rows, cfg)
    assert summary["games_with_lines"] == 2


def test_engine_prior_blend_early_season():
    eng = PaceEngine(NFL_PACE_CONFIG)
    proj = eng.project("AAA", "BBB")
    assert proj["total"] > 0
