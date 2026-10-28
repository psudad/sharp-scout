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
    is_season_long_absence,
    margin_impact_pts,
    offense_impact_pts,
    resolve_player_rate_row,
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
    rows, excluded = team_absence_rows("PHI", injuries, rates=rates)
    assert len(rows) == 1
    assert rows[0]["weight"] == 0.5
    assert not excluded


def test_missing_rate_row_skipped_without_stats(monkeypatch):
    monkeypatch.setattr(
        "sharp_scout.nba.score_model.player_impact.build_supplemental_rate_row",
        lambda *a, **k: None,
    )
    injuries = [
        {
            "player": "Jose Alvarado",
            "team": "NYK",
            "status": "Out",
            "detail": "Out Tuesday.",
        }
    ]
    rows, excluded = team_absence_rows("NYK", injuries, rates={})
    assert not excluded
    assert rows == []


def test_injury_only_edge_does_not_qualify_without_raw():
    from sharp_scout.nba.score_model.pace_qualify import qualifies_spread

    ok, gap, _, _ = qualifies_spread(
        raw_margin=1.0,
        injury_margin=5.0,
        spread_home=-3.0,
        min_gap=3.0,
        require_raw=True,
    )
    assert not ok
    ok2, gap2, _, _ = qualifies_spread(
        raw_margin=6.0,
        injury_margin=7.0,
        spread_home=-3.0,
        min_gap=3.0,
        require_raw=True,
    )
    assert ok2 and gap2 >= 3.0


def test_season_long_out_excluded_not_adjusted():
    rates = {
        "POR|shaedon sharpe": {
            "player_name": "Shaedon Sharpe",
            "team": "POR",
            "minutes": 30,
            "current_season_gp": 0,
            "played_this_season": False,
            "pts_per_min": 0.5,
            "reb_per_min": 0.1,
            "ast_per_min": 0.05,
            "usage_share": 0.25,
        }
    }
    injuries = [
        {
            "player": "Shaedon Sharpe",
            "team": "POR",
            "status": "Out",
            "detail": "Sharpe suffered a torn meniscus and is expected to miss six months.",
        }
    ]
    rows, excluded = team_absence_rows("POR", injuries, rates=rates)
    assert not rows
    assert len(excluded) == 1
    assert excluded[0]["reason"] == "out all season"


def test_is_season_long_absence_patterns():
    assert is_season_long_absence(detail="expected to miss six months")
    assert is_season_long_absence(detail="out for the season")
    assert not is_season_long_absence(detail="ruled out for Tuesday's game")


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
