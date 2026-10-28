"""CFB 2026 drive Monte Carlo — smoke tests."""

from __future__ import annotations

from sharp_scout.football_pace.cfb_sim.drives import load_drive_table, season_actual_scoring
from sharp_scout.football_pace.cfb_sim.profiles import build_profiles
from sharp_scout.football_pace.cfb_sim.adjustments import build_adjusted_profiles
from sharp_scout.football_pace.cfb_sim.simulate import simulate_matchup


def test_drive_table_non_empty():
    drives = load_drive_table(2026)
    assert len(drives) > 1000


def test_sim_median_scores_sane():
    drives = load_drive_table(2026)
    profiles = build_profiles(drives)
    assert len(profiles) > 20
    teams = list(profiles.keys())[:2]
    sim = simulate_matchup(teams[0], teams[1], profiles, n_sims=500, seed=1)
    assert 0 <= sim.home_median <= 75
    assert 0 <= sim.away_median <= 75
    assert sim.total_median <= 120


def test_season_actual_scoring():
    drives = load_drive_table(2026)
    s = season_actual_scoring(drives)
    assert s["team_pts_mean"] > 10


def test_adjusted_bundle_runs():
    drives = load_drive_table(2026)
    profiles = build_profiles(drives)
    teams = list(profiles.keys())[:2]
    bundle = build_adjusted_profiles(teams[0], teams[1], profiles, {})
    base = simulate_matchup(teams[0], teams[1], profiles, n_sims=200, seed=3)
    adj = simulate_matchup(
        teams[0],
        teams[1],
        profiles,
        home_profile=bundle.home,
        away_profile=bundle.away,
        n_sims=200,
        seed=4,
    )
    assert 0 <= adj.total_median <= 120
    assert base.total_median > 0
