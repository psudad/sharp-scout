"""Unit tests for odds math, MC cover probs, filters — no network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sharp_scout.data.action_network import mock_splits
from sharp_scout.data.odds_api import mock_odds_events
from sharp_scout.phase1.ratings import TeamPower, matchup_means
from sharp_scout.phase2.monte_carlo import p_true_for_market, simulate_game
from sharp_scout.phase3.market import discover_edges, fair_probs_from_two_way
from sharp_scout.phase4.filters import attach_filters, reverse_line_movement, validate_edge
from sharp_scout.utils.odds import american_to_implied_prob, expected_value, normalize_team


def test_normalize_team():
    assert normalize_team("Kansas City Chiefs") == "KC"
    assert normalize_team("LAR") == "LAR"
    assert normalize_team("Washington Commanders") == "WAS"


def test_american_and_ev():
    assert abs(american_to_implied_prob(-110) - 0.5238) < 0.001
    assert abs(american_to_implied_prob(100) - 0.5) < 1e-9
    # Fair coin at -110 is negative EV
    assert expected_value(0.5, -110) < 0
    # 55% at -110 is positive EV
    assert expected_value(0.55, -110) > 0


def test_devig_sums_to_one():
    a, b = fair_probs_from_two_way(-110, -110)
    assert abs(a + b - 1.0) < 1e-9
    assert abs(a - 0.5) < 0.01


def test_monte_carlo_home_favorite():
    sim = simulate_game("BUF", "KC", mu_home=28, mu_away=22, n_sims=5000, seed=1)
    assert sim.p_home_win > 0.55
    assert sim.model_total == 50
    p_cover = p_true_for_market(sim, "spreads", "home", -3.0)
    assert 0.4 < p_cover < 0.75


def test_matchup_means_direction():
    ratings = {
        "KC": TeamPower("KC", 0.1, 0.05, 0, 0, 0, 0, 0.1, 0, 0.15),
        "NYJ": TeamPower("NYJ", -0.05, -0.02, 0, 0, 0, 0, -0.05, -0.08, -0.07),
    }
    m = matchup_means("KC", "NYJ", ratings, home_boost=2.2)
    assert m["mu_home"] > m["mu_away"]
    assert m["model_spread"] < 0  # home favored


def test_pipeline_filters_demo_splits():
    splits = mock_splits()
    block = splits[0]["markets"]["spread"]
    # Public on BUF (home 72%) but line moved from -1.5 to -2.5 toward home... 
    # For away (KC) RLM: public home, line moved toward home → not RLM for away
    # Money gap on away: money 59% vs tickets 28% → gap 31% OK
    ok, _ = reverse_line_movement(block, "away", "spreads")
    # line -1.5 → -2.5 means moved toward home, public is home → no RLM for away
    assert ok is False

    from sharp_scout.phase3.market import EdgeCandidate

    edge = EdgeCandidate(
        event_id="demo-kc-buf",
        home_team="BUF",
        away_team="KC",
        market="spreads",
        side="away",
        line=-2.5,
        book="draftkings",
        price=-105,
        p_true=0.56,
        p_mkt=0.51,
        edge=0.04,
        sharp_book="pinnacle",
        sharp_price=-110,
        model_spread=-1.0,
        model_total=48.0,
    )
    fr = validate_edge(edge, splits)
    assert fr.flags["money_split"] is True
    assert fr.passed is True


def test_discover_edges_runs_on_mock():
    events = mock_odds_events()
    ratings = {
        "BUF": TeamPower("BUF", 0.02, 0.02, 0, 0, 0, 0, 0, 0, 0.04),
        "KC": TeamPower("KC", 0.12, 0.06, 0, 0, 0, 0, 0, 0, 0.18),
    }
    m = matchup_means("BUF", "KC", ratings, home_boost=2.0)
    # Push KC strongly so away covers
    sim = simulate_game("BUF", "KC", m["mu_home"] - 4, m["mu_away"] + 6, n_sims=3000, seed=2)
    edges = discover_edges(events[0], sim, ev_threshold=0.01)
    assert isinstance(edges, list)
    filtered = attach_filters(edges, mock_splits())
    assert len(filtered) == len(edges)