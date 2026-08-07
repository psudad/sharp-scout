"""Player props + pregame scheduler tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.props.filters import validate_prop_edge
from sharp_scout.props.markets import PropEdge, discover_prop_edges, mock_prop_event
from sharp_scout.props.simulate import p_true_over_under, simulate_prop
from sharp_scout.props.usage import (
    _demo_usage,
    apply_game_script,
    find_player,
    reallocate_targets,
)
from sharp_scout.data.odds_api import mock_odds_events
from sharp_scout.scheduler.pregame import find_due_windows, mark_fired
from sharp_scout.props.pipeline import run_props_pipeline


def test_usage_script_underdog_pass_boost():
    u = _demo_usage()["stephon diggs"]
    boosted = apply_game_script(u, team_spread=7.0, team_total=48.0, is_home=False)
    assert boosted.exp_targets > u.exp_targets


def test_reallocate_inactive():
    profiles = _demo_usage()
    out = reallocate_targets(profiles, "BUF", ["Stefon Diggs"], redistribute_frac=0.4)
    assert out["stephon diggs"].inactive is True
    assert out["stephon diggs"].exp_targets < profiles["stephon diggs"].exp_targets


def test_gamma_reception_yards_distribution():
    u = _demo_usage()["stephon diggs"]
    sim = simulate_prop(u, "player_reception_yds", n_sims=3000, seed=1)
    assert sim.mean > 50
    p_over = p_true_over_under(sim, "over", 74.5)
    assert 0.2 < p_over < 0.8


def test_negbin_receptions():
    u = _demo_usage()["travis kelce"]
    sim = simulate_prop(u, "player_receptions", n_sims=2000, seed=2)
    assert sim.median >= 3


def test_prop_edges_and_filter():
    ev = mock_prop_event(mock_odds_events()[0])
    profiles = _demo_usage()
    from sharp_scout.props.markets import build_sims_for_event
    from sharp_scout.props.simulate import CORE_PROP_MARKETS

    sims = build_sims_for_event(ev, profiles, profiles, CORE_PROP_MARKETS, n_sims=1500)
    edges = discover_prop_edges(ev, sims, ev_threshold=0.01)
    assert isinstance(edges, list)
    if edges:
        fr = validate_prop_edge(edges[0], wind_mph=5)
        assert fr.tier in ("play", "lean", "rejected", "candidate")


def test_weather_rejects_pass_over():
    edge = PropEdge(
        event_id="x",
        home_team="BUF",
        away_team="KC",
        player_name="Josh Allen",
        team="BUF",
        market="player_pass_yds",
        side="over",
        line=259.5,
        book="draftkings",
        price=-110,
        p_true=0.58,
        p_mkt=0.52,
        edge=0.05,
        model_mean=270,
        model_median=265,
        is_alternate=False,
    )
    fr = validate_prop_edge(edge, wind_mph=18)
    assert fr.passed is False
    assert fr.flags["weather_ok"] is False


def test_pregame_windows(tmp_path):
    now = datetime.now(timezone.utc)
    events = [
        {
            "event_id": "g1",
            "home_team": "BUF",
            "away_team": "KC",
            "commence_time": now + timedelta(hours=3, minutes=5),
        },
        {
            "event_id": "g2",
            "home_team": "SF",
            "away_team": "SEA",
            "commence_time": now + timedelta(hours=12),
        },
    ]
    hits = find_due_windows(events, windows_hours=[12, 3, 1], tolerance_minutes=30, now=now, state={"fired": {}})
    keys = {h.state_key for h in hits}
    assert any("T-3h" in k for k in keys)
    assert any("T-12h" in k for k in keys)
    # Second call after mark should not re-fire
    state_path = tmp_path / "state.json"
    from sharp_scout.scheduler import pregame as pg

    pg.STATE_PATH = state_path
    mark_fired(hits, path=state_path)
    hits2 = find_due_windows(events, windows_hours=[12, 3, 1], tolerance_minutes=30, now=now, state=pg.load_state(state_path))
    assert hits2 == []


def test_props_pipeline_demo():
    result = run_props_pipeline(demo=True, skip_pbp=True, update_ledger=False, build_pages=False)
    assert result["n_events"] >= 1
    assert "plays" in result
    assert find_player(_demo_usage(), "Josh Allen") is not None
