"""Player props + pregame scheduler tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
from sharp_scout.scheduler.pregame import find_due_windows, mark_fired, run_due_pregame
from sharp_scout.props.pipeline import run_props_pipeline


def test_apply_matchup_boosts_pass_and_rush():
    from sharp_scout.props.usage import PlayerUsage, apply_matchup

    wr = PlayerUsage("x", "Test WR", "BUF", "WR", exp_targets=8, exp_receptions=5, exp_rec_yards=70)
    boosted = apply_matchup(wr, opp_pass_epa_allowed=0.12, opp_rush_epa_allowed=0.0)
    assert boosted.exp_targets > wr.exp_targets

    rb = PlayerUsage("y", "Test RB", "BUF", "RB", exp_rush_att=15, exp_rush_yards=65)
    rush_boost = apply_matchup(rb, opp_pass_epa_allowed=0.0, opp_rush_epa_allowed=0.10)
    assert rush_boost.exp_rush_yards > rb.exp_rush_yards


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


@pytest.fixture
def isolated_artifacts(tmp_path, monkeypatch):
    """Keep demo pipeline runs out of the real artifacts dir.

    Without this, running the test suite overwrites artifacts/latest_props.json and
    latest_signals.json with demo output, so a later report or site build silently shows
    KC @ BUF mock data instead of the live slate.
    """
    from sharp_scout.ncaaf import pipeline as ncaaf_pipeline
    from sharp_scout.pipeline import run as side_run
    from sharp_scout.props import pipeline as props_pipeline

    art = tmp_path / "artifacts"
    art.mkdir()
    for module in (props_pipeline, side_run, ncaaf_pipeline):
        monkeypatch.setattr(module, "ARTIFACTS_DIR", art, raising=False)
    return art


def test_demo_pregame_does_not_refire_same_window(tmp_path, isolated_artifacts):
    """Demo mode must respect schedule_state (cron was re-firing every 30 min)."""
    from sharp_scout.scheduler import pregame as pg

    pg.STATE_PATH = tmp_path / "state.json"
    first = run_due_pregame(demo=True, build_pages=False, skip_pbp=True)
    assert first["ran"] is True
    second = run_due_pregame(demo=True, build_pages=False, skip_pbp=True)
    assert second["ran"] is False
    assert second["hits"] == []


def test_props_pipeline_demo(isolated_artifacts):
    result = run_props_pipeline(demo=True, skip_pbp=True, update_ledger=False, build_pages=False)
    assert (isolated_artifacts / "latest_props.json").exists()
    assert result["n_events"] >= 1
    assert "plays" in result
    assert find_player(_demo_usage(), "Josh Allen") is not None


def test_normalize_pbp_keeps_receiving_columns():
    """The column allowlist silently dropped every receiving field, which zeroed out
    target/reception/yardage baselines for all pass-catchers."""
    import pandas as pd

    from sharp_scout.data.nflfastr import _normalize_pbp

    raw = pd.DataFrame(
        {
            "season": [2025],
            "week": [1],
            "game_id": ["2025_01_NE_SEA"],
            "posteam": ["SEA"],
            "play_type": ["pass"],
            "epa": [0.4],
            "pass": [1],
            "rush": [0],
            "yards_gained": [12],
            "receiver_player_name": ["J.Smith-Njigba"],
            "receiver_player_id": ["00-0038543"],
            "passer_player_id": ["00-0035710"],
            "rusher_player_id": [None],
            "complete_pass": [1],
            "air_yards": [8],
            "receiving_yards": [12],
            "passing_yards": [12],
            "rushing_yards": [0],
            "touchdown": [0],
            "pass_touchdown": [0],
            "rush_touchdown": [0],
            "yardline_100": [45],
            "cpoe": [3.2],
            "sack": [0],
        }
    )
    out = _normalize_pbp(raw)
    for col in (
        "receiver_player_name",
        "receiver_player_id",
        "complete_pass",
        "air_yards",
        "receiving_yards",
        "passing_yards",
        "rushing_yards",
        "pass_touchdown",
        "yardline_100",
        "cpoe",
    ):
        assert col in out.columns, f"{col} dropped by _normalize_pbp"


def test_market_without_usage_is_skipped_not_defaulted():
    """A player with no receiving baseline used to simulate at ~1 yard, making every
    'under' a ~100% certainty and producing 100%+ EV."""
    from sharp_scout.props.usage import PlayerUsage

    empty = PlayerUsage("x", "No Data Guy", "SEA", "WR")
    for market in ("player_reception_yds", "player_receptions", "player_rush_yds", "player_pass_yds"):
        with pytest.raises(ValueError):
            simulate_prop(empty, market, n_sims=200)


def test_implausible_edge_rejected():
    edge = _edge(p_true=0.999, p_mkt=0.55, ev=1.8)
    fr = validate_prop_edge(edge)
    assert fr.passed is False
    assert fr.flags["plausible"] is False


def test_model_market_disagreement_rejected():
    """A 25-point gap against the whole market is model error, not edge."""
    edge = _edge(p_true=0.80, p_mkt=0.55, ev=0.20)
    fr = validate_prop_edge(edge)
    assert fr.passed is False
    assert fr.flags["plausible"] is False


def test_one_sided_market_rejected():
    """With only one side quoted there is no no-vig anchor, so nothing validates it."""
    edge = _edge(p_true=0.72, p_mkt=0.55, ev=0.20)
    edge.p_mkt = None
    fr = validate_prop_edge(edge)
    assert fr.passed is False
    assert fr.flags["plausible"] is False


def test_small_disagreement_still_passes():
    edge = _edge(p_true=0.58, p_mkt=0.52, ev=0.05)
    fr = validate_prop_edge(edge)
    assert fr.flags["plausible"] is True
    assert fr.passed is True


def test_find_player_refuses_ambiguous_surname():
    """Bare-surname matching returned whichever player came first in the dict, which
    attributed one player's projection to another."""
    from sharp_scout.props.usage import PlayerUsage

    profiles = {
        "mike williams": PlayerUsage("a", "Mike Williams", "NYJ", "WR", exp_targets=5),
        "mark williams": PlayerUsage("b", "Mark Williams", "SEA", "TE", exp_targets=3),
    }
    # Exact name always wins.
    assert find_player(profiles, "Mike Williams").team == "NYJ"
    # No first-initial match at all → do not guess.
    assert find_player(profiles, "Jameson Williams") is None
    # Two players share initial + surname → ambiguous, so skip rather than pick one.
    assert find_player(profiles, "Malik Williams") is None
    # Unambiguous initial + surname still resolves.
    assert find_player(profiles, "Marcus Kelce") is None
    assert find_player(_demo_usage(), "Stefon Diggs").team == "BUF"


def test_sims_exclude_players_not_in_the_game():
    from sharp_scout.props.markets import build_sims_for_event
    from sharp_scout.props.simulate import CORE_PROP_MARKETS
    from sharp_scout.props.usage import PlayerUsage

    ev = mock_prop_event(mock_odds_events()[0])
    # Josh Allen re-rostered onto a team that is not playing in this event.
    profiles = dict(_demo_usage())
    profiles["josh allen"] = PlayerUsage(
        "josh allen", "Josh Allen", "DEN", "QB", exp_pass_att=34, exp_pass_yards=265, games=10
    )
    sims = build_sims_for_event(ev, profiles, profiles, CORE_PROP_MARKETS, n_sims=400)
    assert not any(key[0] == "josh allen" for key in sims)


def test_discover_prop_edges_applies_calibrator():
    """Raw simulated probability must be calibrated before EV, and kept for audit."""
    from sharp_scout.props.markets import build_sims_for_event
    from sharp_scout.props.simulate import CORE_PROP_MARKETS

    ev = mock_prop_event(mock_odds_events()[0])
    profiles = _demo_usage()
    sims = build_sims_for_event(ev, profiles, profiles, CORE_PROP_MARKETS, n_sims=2000)

    # Shrink every probability hard toward a coin flip.
    edges = discover_prop_edges(
        ev, sims, ev_threshold=-1.0, calibrate=lambda p, _market: 0.5 + (p - 0.5) * 0.1
    )
    assert edges, "expected candidate edges from the demo event"
    for e in edges:
        assert e.p_raw is not None
        assert e.p_true == pytest.approx(0.5 + (e.p_raw - 0.5) * 0.1, abs=1e-9)
        assert 0.45 <= e.p_true <= 0.55


def test_calibrated_over_under_stay_complementary():
    """Calibrating each side independently let both sides of one line read +EV."""
    from sharp_scout.props.markets import build_sims_for_event
    from sharp_scout.props.simulate import CORE_PROP_MARKETS

    ev = mock_prop_event(mock_odds_events()[0])
    profiles = _demo_usage()
    sims = build_sims_for_event(ev, profiles, profiles, CORE_PROP_MARKETS, n_sims=2000)

    # A deliberately lopsided calibrator, the kind that broke the invariant.
    edges = discover_prop_edges(
        ev, sims, ev_threshold=-1.0, calibrate=lambda p, _m: min(1.0, p * 1.3 + 0.05)
    )
    by_line: dict[tuple, dict[str, float]] = {}
    for e in edges:
        by_line.setdefault((e.player_name, e.market, e.line), {})[e.side] = e.p_true

    paired = [v for v in by_line.values() if {"over", "under"} <= set(v)]
    assert paired, "expected at least one two-way line in the demo event"
    for probs in paired:
        assert probs["over"] + probs["under"] == pytest.approx(1.0, abs=1e-9)


def _edge(*, p_true: float, p_mkt: float, ev: float) -> PropEdge:
    return PropEdge(
        event_id="x",
        home_team="SEA",
        away_team="NE",
        player_name="Test Player",
        team="SEA",
        market="player_reception_yds",
        side="under",
        line=60.5,
        book="draftkings",
        price=-110,
        p_true=p_true,
        p_mkt=p_mkt,
        edge=ev,
        model_mean=55.0,
        model_median=52.0,
        is_alternate=False,
    )
