"""NBA injury-adjusted score model (offline math + live roster assignment)."""

from __future__ import annotations

from sharp_scout.nba.rosters import (
    clear_roster_cache,
    player_team_from_roster,
    resolve_player_team_for_game,
)
from sharp_scout.nba.score_model.injury_adjust import (
    STATUS_WEIGHT,
    apply_team_adjustments,
    scope_injuries_to_game,
    status_weight,
    team_absence_rows,
)
from sharp_scout.nba.score_model.player_impact import (
    MAX_OFF_PTS_GAME,
    margin_impact_pts,
    offense_impact_pts,
)


def test_status_weights():
    assert status_weight("Out") == STATUS_WEIGHT["out"]
    assert status_weight("DOUBTFUL") == 0.75
    assert status_weight("Questionable") == 0.5
    assert status_weight("Active") == 0.0


def test_offense_impact_capped():
    row = {
        "player_name": "Star",
        "team": "PHI",
        "minutes": 38.0,
        "pts_per_min": 0.85,
        "reb_per_min": 0.15,
        "ast_per_min": 0.22,
        "usage_share": 0.34,
    }
    assert offense_impact_pts(row) <= MAX_OFF_PTS_GAME
    assert margin_impact_pts(row) >= offense_impact_pts(row)


def test_apply_team_adjustments_lowers_total_when_star_out():
    home_abs = [
        {
            "kind": "absence",
            "off_pts": -5.0,
            "def_pts": -2.0,
            "pace_pts": -1.0,
        }
    ]
    h, a, m, t = apply_team_adjustments(110.0, 108.0, home_abs=home_abs, away_abs=[])
    assert h < 110.0
    assert t < 218.0
    assert m == h - a


def test_scope_injuries_uses_roster_not_reported_team(monkeypatch):
    monkeypatch.setattr(
        "sharp_scout.nba.score_model.injury_adjust.resolve_player_team_for_game",
        lambda name, home, away, reported_team=None, season=2027: (
            "PHI" if name == "LeBron James" and home == "PHI" and away == "BOS" else None
        ),
    )
    scoped = scope_injuries_to_game(
        [{"player": "LeBron James", "team": "LAL", "status": "Out"}],
        "PHI",
        "BOS",
    )
    assert len(scoped) == 1
    assert scoped[0]["team"] == "PHI"


def test_team_absence_respects_status_weight():
    rates = {
        "PHI|joel embiid": {
            "player_name": "Joel Embiid",
            "team": "PHI",
            "minutes": 34,
            "pts_per_min": 0.8,
            "reb_per_min": 0.14,
            "ast_per_min": 0.12,
            "usage_share": 0.32,
        }
    }
    injuries = [{"player": "Joel Embiid", "team": "PHI", "status": "Questionable"}]
    rows = team_absence_rows("PHI", injuries, rates=rates)
    assert len(rows) == 1
    assert rows[0]["weight"] == 0.5


def test_live_roster_assigns_lebron_to_phi():
    clear_roster_cache()
    team = player_team_from_roster("LeBron James")
    assert team == "PHI"
    resolved = resolve_player_team_for_game(
        "LeBron James",
        home="PHI",
        away="BOS",
        reported_team="LAL",
    )
    assert resolved == "PHI"
    assert resolve_player_team_for_game("LeBron James", home="LAL", away="BOS", reported_team="LAL") is None
