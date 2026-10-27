"""Injury adjustment layer for shadow football pace model."""

from __future__ import annotations

from sharp_scout.football_pace.injury_adjust import (
    apply_injury_adjustment,
    normalize_injury_status,
    status_weight,
    team_injury_deltas,
)
from sharp_scout.football_pace.player_value import PlayerValueTracker


def test_status_weights():
    assert status_weight("Out") == 1.0
    assert status_weight("Questionable") > 0
    assert status_weight("Active") == 0.0
    assert normalize_injury_status("Injured Reserve") == "injured reserve"


def test_qb_out_lowers_offense():
    tr = PlayerValueTracker("nfl")
    tr.seed_roster("KC", [{"player": "Patrick Mahomes", "position": "QB", "depth_rank": 1}])
    tr.observe_game_touches(
        game_id="g1",
        touches=[("KC", "Patrick Mahomes", 40), ("KC", "Travis Kelce", 8)],
    )
    deltas = team_injury_deltas(
        tr,
        [{"player": "Patrick Mahomes", "team": "KC", "position": "QB", "status": "Out"}],
        roster_names=["Patrick Mahomes", "Travis Kelce"],
    )
    assert deltas["off_loss"] > 2.0


def test_apply_injury_moves_total():
    base = {"home_pts": 24.0, "away_pts": 21.0, "margin": 3.0, "total": 45.0}
    adj = apply_injury_adjustment(base, home_off_loss=2.0, home_def_loss=0, away_off_loss=0, away_def_loss=0)
    assert adj["total"] == 43.0
    assert adj["margin"] == 1.0
