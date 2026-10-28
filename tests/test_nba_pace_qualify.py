"""Pace qualification thresholds and raw+injury rules."""

from __future__ import annotations

from sharp_scout.nba.score_model.engine import V2Engine, V2Params
from sharp_scout.nba.score_model.pace_qualify import pace_min_gap_pts, pace_display_pick_from_snapshot


def test_early_season_min_gap_higher():
    engine = V2Engine(params=V2Params(), stage=3)
    engine.team_games = {"BOS": 4, "NYK": 4}
    assert pace_min_gap_pts(engine=engine, home="BOS", away="NYK") == 4.5
    engine.team_games = {"BOS": 20, "NYK": 20}
    assert pace_min_gap_pts(engine=engine, home="BOS", away="NYK") == 3.0


def test_display_pick_requires_raw_and_injury_gap():
    engine = V2Engine(params=V2Params(), stage=3)
    engine.team_games = {"BOS": 20, "NYK": 20}
    snap = {
        "margin": 2.0,
        "total": 224.0,
        "injury_margin": 6.0,
        "injury_total": 224.0,
        "lines": {"consensus_spread_home": -4.0, "consensus_total": 225.0},
    }
    assert pace_display_pick_from_snapshot(snap, home="BOS", away="NYK", engine=engine) is None
    snap["margin"] = 8.0
    snap["injury_margin"] = 9.0
    pick = pace_display_pick_from_snapshot(snap, home="BOS", away="NYK", engine=engine)
    assert pick is not None
    assert pick["kind"] == "spread"
