"""NBA score-model paper track + model filter (offline)."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.nba.score_model.model_filter import (
    _model_pick_margin,
    alignment_for_play,
    model_view_for_event,
)
from sharp_scout.nba.score_model.injury_lag import load_store, record_injury_lag_scan, save_store as save_injury_store
from sharp_scout.nba.score_model.player_impact import example_impacts, margin_impact_pts
from sharp_scout.nba.score_model.paper import (
    is_live_paper_event_id,
    load_paper_store,
    record_score_model_scan,
    save_paper_store,
    summarize_score_paper,
    void_score_paper_outside_horizon,
)
from sharp_scout.nba.score_model.engine import V2Engine, V2Params


def _mock_event(
    *,
    eid: str = "0123456789abcdef0123456789ab",
    home: str = "BOS",
    away: str = "NYK",
) -> dict:
    return {
        "event_id": eid,
        "home_team": home,
        "away_team": away,
        "commence_time": datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc),
        "bookmakers": {
            "pinnacle": {
                "key": "pinnacle",
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -4.5, "price": -110},
                        {"side": "away", "point": 4.5, "price": -110},
                    ],
                    "totals": [
                        {"side": "over", "point": 220.5, "price": -110},
                        {"side": "under", "point": 220.5, "price": -110},
                    ],
                },
            },
            "draftkings": {
                "key": "draftkings",
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -4.5, "price": -108},
                        {"side": "away", "point": 4.5, "price": -112},
                    ],
                    "totals": [
                        {"side": "over", "point": 220.0, "price": -110},
                        {"side": "under", "point": 220.0, "price": -110},
                    ],
                },
            },
        },
    }


def test_spread_sign_home_favored_agrees_with_home_pick():
    """Positive proj_margin = home ahead; home spread -4.5 needs ~+4.5 to take home."""
    spread = -4.5
    proj = 5.0
    assert _model_pick_margin(proj, spread) == "home"
    view = {
        "proj_margin": proj,
        "model_spread_side": "home",
        "margin_edge_pts": proj + spread,
    }
    assert alignment_for_play({"market": "spreads", "side": "home"}, view)["model_alignment"] == "agree"
    assert alignment_for_play({"market": "spreads", "side": "away"}, view)["model_alignment"] == "disagree"


def test_spread_sign_model_favors_dog_when_proj_below_market():
    """BOS -4.5 with proj_margin +2 → edge negative → model side away (matches smoke)."""
    spread = -4.5
    proj = 2.0
    assert _model_pick_margin(proj, spread) == "away"
    view = {"proj_margin": proj, "model_spread_side": "away", "margin_edge_pts": proj + spread}
    assert alignment_for_play({"market": "spreads", "side": "away"}, view)["model_alignment"] == "agree"


def test_margin_impact_star_not_raw_points():
    row = {
        "player_name": "LaMelo Ball",
        "team": "CHA",
        "minutes": 32.0,
        "pts_per_min": 0.72,
        "reb_per_min": 0.18,
        "ast_per_min": 0.22,
        "usage_share": 0.28,
    }
    impact = margin_impact_pts(row)
    assert 2.0 <= impact <= 8.0
    assert impact < 12.0


def _patch_lamelo_on_cha(monkeypatch):
    monkeypatch.setattr(
        "sharp_scout.nba.score_model.injury_lag.resolve_player_team_for_game",
        lambda name, home, away, reported_team=None, season=2027: (
            "CHA" if str(name).lower() == "lamelo ball" and home == "CHA" else None
        ),
    )


def test_injury_first_scan_seeds_without_entry(tmp_path, monkeypatch):
    store_path = tmp_path / "injury.json"
    monkeypatch.setattr("sharp_scout.nba.score_model.injury_lag.PAPER_PATH", store_path)
    _patch_lamelo_on_cha(monkeypatch)
    monkeypatch.setattr(
        "sharp_scout.nba.score_model.injury_lag.fetch_espn_nba_injuries",
        lambda: [{"player": "LaMelo Ball", "team": "CHA", "status": "Out"}],
    )
    n = record_injury_lag_scan([_mock_event(home="CHA", away="MIA", eid="e2")])
    assert n == 0
    store = load_store(store_path)
    assert len(store["entries"]) == 0
    assert store["player_status"]["CHA|lamelo ball"] == "out"


def test_injury_logs_transition_with_prior_lines(tmp_path, monkeypatch):
    store_path = tmp_path / "injury.json"
    monkeypatch.setattr("sharp_scout.nba.score_model.injury_lag.PAPER_PATH", store_path)
    _patch_lamelo_on_cha(monkeypatch)
    ev = _mock_event(home="CHA", away="MIA", eid="e2")
    monkeypatch.setattr(
        "sharp_scout.nba.score_model.injury_lag.fetch_espn_nba_injuries",
        lambda: [],
    )
    record_injury_lag_scan([ev])
    store = load_store(store_path)
    store["player_status"]["CHA|lamelo ball"] = "questionable"
    save_injury_store(store, store_path)
    monkeypatch.setattr(
        "sharp_scout.nba.score_model.injury_lag.fetch_espn_nba_injuries",
        lambda: [{"player": "LaMelo Ball", "team": "CHA", "status": "Out"}],
    )
    n = record_injury_lag_scan([ev])
    assert n == 1
    store = load_store(store_path)
    assert store["entries"][0]["line_at_prior_scan"]
    assert store["entries"][0]["line_at_detection"]


def test_example_impacts_ten_players():
    ex = example_impacts(10)
    assert len(ex) == 10


def test_model_alignment_spread_agree():
    engine = V2Engine(params=V2Params(), stage=1)
    view = {
        "proj_margin": 6.0,
        "proj_total": 225.0,
        "consensus_spread_home": -4.5,
        "consensus_total": 220.0,
        "model_spread_side": "home",
        "model_total_side": "over",
        "margin_edge_pts": 1.5,
        "total_edge_pts": 5.0,
    }
    play = {"market": "spreads", "side": "home"}
    assert alignment_for_play(play, view)["model_alignment"] == "agree"
    play2 = {"market": "spreads", "side": "away"}
    assert alignment_for_play(play2, view)["model_alignment"] == "disagree"


def test_record_score_model_scan_tmp(tmp_path, monkeypatch):
    store_path = tmp_path / "paper.json"
    monkeypatch.setattr(
        "sharp_scout.nba.score_model.paper.PAPER_PATH",
        store_path,
    )
    engine = V2Engine(params=V2Params(), stage=3)
    ev = _mock_event()
    now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    record_score_model_scan(
        [ev], engine=engine, store=load_paper_store(store_path), now=now, horizon_hours=36.0
    )
    store = load_paper_store(store_path)
    assert len(store["games"]) == 1
    assert store["games"][0]["scans"]
    snap = store["games"][0]["scans"][0]
    assert "margin" in snap and "p_cover_home_consensus" in snap


def test_summarize_score_paper_empty():
    assert summarize_score_paper({"games": []}) == {"n_graded": 0}


def test_void_score_paper_outside_horizon(tmp_path):
    store_path = tmp_path / "paper.json"
    scan_at = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    store = {
        "games": [
            {
                "event_id": "near",
                "home": "BOS",
                "away": "NYK",
                "kickoff": "2026-10-26T23:00:00+00:00",
                "scans": [{"at": scan_at.isoformat(), "margin": 1.0, "total": 220.0}],
            },
            {
                "event_id": "xmas",
                "home": "LAL",
                "away": "GSW",
                "kickoff": "2026-12-25T17:00:00+00:00",
                "scans": [{"at": scan_at.isoformat(), "margin": 2.0, "total": 230.0}],
            },
        ]
    }
    n = void_score_paper_outside_horizon(store, horizon_hours=36.0, now=scan_at)
    assert n == 1
    assert store["games"][1]["exclude_reason"] == "kickoff_outside_horizon"
    assert summarize_score_paper(store)["n_graded"] == 0


def test_is_live_paper_event_id_rejects_test():
    assert not is_live_paper_event_id("test")
    assert is_live_paper_event_id("b9f6f078c66480af12ca8bcc44969097")


def test_load_paper_store_drops_test_event(tmp_path):
    store_path = tmp_path / "paper.json"
    store_path.write_text(
        '{"games":[{"event_id":"test","home":"BOS","away":"NYK","scans":[]},'
        '{"event_id":"abc1234567890","home":"BOS","away":"NYK","scans":[]}]}'
    )
    from sharp_scout.nba.score_model import paper as paper_mod

    old = paper_mod.PAPER_PATH
    try:
        paper_mod.PAPER_PATH = store_path
        store = load_paper_store(store_path)
        assert len(store["games"]) == 1
        assert store["games"][0]["event_id"] == "abc1234567890"
    finally:
        paper_mod.PAPER_PATH = old


def test_record_score_model_skips_far_kickoff(tmp_path, monkeypatch):
    store_path = tmp_path / "paper.json"
    monkeypatch.setattr("sharp_scout.nba.score_model.paper.PAPER_PATH", store_path)
    engine = V2Engine(params=V2Params(), stage=3)
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    near = _mock_event(eid="0123456789abcdef0123456789aa", home="BOS", away="NYK")
    far = _mock_event(eid="0123456789abcdef0123456789bb", home="LAL", away="GSW")
    far["commence_time"] = datetime(2026, 12, 25, 17, 0, tzinfo=timezone.utc)
    record_score_model_scan([near, far], engine=engine, now=now, horizon_hours=36.0)
    store = load_paper_store(store_path)
    ids = {g["event_id"] for g in store["games"]}
    assert near["event_id"] in ids
    assert far["event_id"] not in ids


def test_model_view_uses_engine():
    engine = V2Engine(params=V2Params(), stage=1)
    view = model_view_for_event(_mock_event(), engine=engine)
    assert view["proj_margin"] is not None
    assert view["proj_total"] is not None
