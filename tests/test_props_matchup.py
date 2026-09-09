"""Opponent matchup tilt helpers for player props."""

from __future__ import annotations

from sharp_scout.phase1.ratings import TeamPower
from sharp_scout.props.matchup import opponent_matchup_tilts


def test_opponent_matchup_tilts_relative_to_league():
    # ``def_epa`` / ``def_ypp`` are oriented higher = better defense.
    ratings = {
        "BUF": TeamPower("BUF", 0.1, 0.2, 0.5, 0.5, 5.5, 0.20, 0.1, 0.0, 0.0),
        "NYJ": TeamPower("NYJ", 0.0, -0.1, 0.5, 0.5, 5.0, -0.15, 0.0, 0.0, 0.0),
    }
    # BUF has the better defense → negative pass-allowed tilt vs NYJ offense.
    pass_buf, rush_buf = opponent_matchup_tilts(ratings, "BUF")
    pass_nyj, rush_nyj = opponent_matchup_tilts(ratings, "NYJ")
    assert pass_buf < pass_nyj
    assert rush_buf < rush_nyj
