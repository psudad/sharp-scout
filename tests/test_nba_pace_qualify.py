"""Pace v1 production + v2 shadow qualification."""

from __future__ import annotations

from sharp_scout.nba.score_model.engine import V2Engine, V2Params
from sharp_scout.nba.score_model.engine_v2 import ShadowV2Engine, ShadowV2Params
from sharp_scout.nba.score_model.pace_v1 import pace_display_pick_from_snapshot, pace_min_gap_pts
from sharp_scout.nba.score_model.pace_v2_qualify import evaluate_pace_pick_v2, pace_min_gap_pts_v2


def test_v1_fixed_three_point_bar():
    engine = V2Engine(params=V2Params(), stage=3)
    engine.team_games = {"BOS": 4, "NYK": 4}
    assert pace_min_gap_pts(engine=engine, home="BOS", away="NYK") == 3.0


def test_v2_early_season_min_gap_higher():
    engine = ShadowV2Engine(params=ShadowV2Params(), stage=3)
    engine.team_games = {"BOS": 4, "NYK": 4}
    assert pace_min_gap_pts_v2(engine=engine, home="BOS", away="NYK") == 4.5
    engine.team_games = {"BOS": 20, "NYK": 20}
    assert pace_min_gap_pts_v2(engine=engine, home="BOS", away="NYK") == 3.0


def test_v2_large_gap_excluded_early_season():
    engine = ShadowV2Engine(params=ShadowV2Params(), stage=3)
    engine.team_games = {"OKC": 2, "LAC": 2}
    snap = {
        "margin": 9.5,
        "total": 220.0,
        "injury_margin": 9.5,
        "injury_total": 220.0,
        "lines": {"consensus_spread_home": -16.5, "consensus_total": 225.0},
    }
    pick, meta = evaluate_pace_pick_v2(snap, home="OKC", away="LAC", engine=engine)
    assert pick is None
    assert meta and meta.get("would_be_pick", {}).get("pick")


def test_v1_allows_injury_only_gap():
    engine = V2Engine(params=V2Params(), stage=3)
    snap = {
        "margin": 1.0,
        "total": 224.0,
        "injury_margin": 7.0,
        "injury_total": 224.0,
        "lines": {"consensus_spread_home": -4.0, "consensus_total": 225.0},
    }
    pick = pace_display_pick_from_snapshot(snap, home="BOS", away="NYK", engine=engine)
    assert pick is not None
    assert pick["kind"] == "spread"
