"""Current-season-only totals shadow (live totals stay legacy)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sharp_scout.nba.score_model.current_season_totals import (
    LEAGUE_AVG_TOTAL,
    project_total_current_season,
    project_total_legacy_prior_blend,
)
from sharp_scout.nba.score_model.engine import HistRow, V2Engine, V2Params, TeamPrior
from sharp_scout.nba.score_model.paper import _proj_row
from sharp_scout.nba.score_model.pace_v1 import pace_display_pick_from_snapshot


def _row(*, home: str, away: str, dt: datetime, pace: float, h_ortg: float, a_ortg: float) -> HistRow:
    return HistRow(
        date=dt,
        home=home,
        away=away,
        home_ortg=h_ortg,
        away_ortg=a_ortg,
        pace=pace,
        home_rest=2,
        away_rest=2,
        home_b2b=0,
        away_b2b=0,
        home_3in4=0,
        away_3in4=0,
        home_travel=0,
        away_travel=0,
        home_alt=0,
        away_alt=0,
        weight=1.0,
    )


def test_current_season_total_ignores_prior_season_history():
    engine = V2Engine(params=V2Params(), stage=3)
    engine.season_priors["DEN"] = TeamPrior(off=118.0, def_=110.0, pace=102.0)
    engine.season_priors["NOP"] = TeamPrior(off=115.0, def_=112.0, pace=101.0)
    engine.team_games.update({"DEN": 3, "NOP": 3})
    engine.history.append(
        _row(
            home="DEN",
            away="NOP",
            dt=datetime(2025, 3, 1, tzinfo=timezone.utc),
            pace=105.0,
            h_ortg=120.0,
            a_ortg=118.0,
        )
    )
    engine.history.append(
        _row(
            home="DEN",
            away="NOP",
            dt=datetime(2026, 10, 20, tzinfo=timezone.utc),
            pace=95.0,
            h_ortg=105.0,
            a_ortg=104.0,
        )
    )
    engine.history.append(
        _row(
            home="NOP",
            away="DEN",
            dt=datetime(2026, 10, 22, tzinfo=timezone.utc),
            pace=94.0,
            h_ortg=106.0,
            a_ortg=103.0,
        )
    )
    kick = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
    cs = project_total_current_season(engine, "NOP", "DEN", game_date=kick)
    legacy = project_total_legacy_prior_blend(engine, "NOP", "DEN", game_date=kick)
    assert cs["total"] < legacy - 5.0
    assert cs["total_diagnostics"]["home"]["games"] >= 1
    assert cs["total_diagnostics"]["away"]["games"] >= 1


def _proj_row_live_fields(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "home_pts",
        "away_pts",
        "margin",
        "total",
        "injury_home_pts",
        "injury_away_pts",
        "injury_margin",
        "injury_total",
        "home_absences",
        "away_absences",
    )
    return {k: row.get(k) for k in keys}


def test_live_projection_unchanged_when_shadow_module_runs(monkeypatch, tmp_path):
    engine = V2Engine(params=V2Params(), stage=3)
    engine.season_priors["MIN"] = TeamPrior(off=120.0, def_=108.0, pace=102.0)
    engine.season_priors["GSW"] = TeamPrior(off=118.0, def_=110.0, pace=100.0)
    engine.team_games.update({"MIN": 4, "GSW": 4})
    engine.history.append(
        _row(
            home="MIN",
            away="GSW",
            dt=datetime(2026, 10, 24, tzinfo=timezone.utc),
            pace=98.0,
            h_ortg=108.0,
            a_ortg=107.0,
        )
    )
    kick = datetime(2026, 10, 29, 23, 0, tzinfo=timezone.utc)
    ev = {
        "event_id": "test-shadow-parity",
        "home_team": "MIN",
        "away_team": "GSW",
        "commence_time": kick,
    }
    lines = {"consensus_total": 227.5, "consensus_spread_home": -3.5}
    at = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc).isoformat()

    baseline = _proj_row_live_fields(
        _proj_row(engine, ev, at=at, lines=lines, prior_status={}, injury_store={})
    )
    pick_base = pace_display_pick_from_snapshot(
        _proj_row(engine, ev, at=at, lines=lines, prior_status={}, injury_store={}),
        home="MIN",
        away="GSW",
        engine=engine,
    )

    import sharp_scout.nba.score_model.totals_shadow as ts

    shadow_path = tmp_path / "shadow.json"
    monkeypatch.setattr(ts, "SHADOW_PATH", shadow_path)
    monkeypatch.setattr(ts, "SHADOW_CSV_PATH", tmp_path / "shadow.csv")

    from sharp_scout.nba.score_model import totals_shadow as ts_mod

    ts_mod.maybe_record_totals_shadow_for_scan(
        engine,
        event_id="test-shadow-parity",
        home="MIN",
        away="GSW",
        kickoff=kick,
        scan_at=at,
        snap=_proj_row(engine, ev, at=at, lines=lines, prior_status={}, injury_store={}),
    )
    with_shadow = _proj_row_live_fields(
        _proj_row(engine, ev, at=at, lines=lines, prior_status={}, injury_store={})
    )
    pick_shadow = pace_display_pick_from_snapshot(
        _proj_row(engine, ev, at=at, lines=lines, prior_status={}, injury_store={}),
        home="MIN",
        away="GSW",
        engine=engine,
    )

    assert baseline == with_shadow
    assert (pick_base or {}).get("pick") == (pick_shadow or {}).get("pick")
    assert shadow_path.exists()
    store = ts.load_totals_shadow(shadow_path)
    assert store.get("pending")


def test_shadow_sidecar_differs_from_legacy_when_priors_dominate():
    engine = V2Engine(params=V2Params(), stage=3)
    engine.season_priors["DEN"] = TeamPrior(off=118.0, def_=110.0, pace=102.0)
    engine.season_priors["NOP"] = TeamPrior(off=115.0, def_=112.0, pace=101.0)
    engine.team_games.update({"DEN": 3, "NOP": 3})
    engine.history.append(
        _row(
            home="DEN",
            away="NOP",
            dt=datetime(2025, 3, 1, tzinfo=timezone.utc),
            pace=105.0,
            h_ortg=120.0,
            a_ortg=118.0,
        )
    )
    engine.history.append(
        _row(
            home="DEN",
            away="NOP",
            dt=datetime(2026, 10, 20, tzinfo=timezone.utc),
            pace=95.0,
            h_ortg=105.0,
            a_ortg=104.0,
        )
    )
    kick = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
    live = engine.project("NOP", "DEN", game_date=kick)
    from sharp_scout.nba.score_model.totals_shadow import compute_shadow_totals_sidecar

    side = compute_shadow_totals_sidecar(
        engine,
        home="DEN",
        away="NOP",
        kickoff=kick,
        lines={"consensus_total": 240.0},
        live_total=float(live["total"]),
        live_injury_total=float(live["total"]),
    )
    assert side["shadow_total"] != side["live_total"]


def test_current_season_totals_differ_for_distinct_matchups():
    """Regression: empty history must not emit the league-average 224.0 for every game."""
    engine = V2Engine(params=V2Params(), stage=3)
    base_dt = datetime(2026, 10, 20, tzinfo=timezone.utc)
    samples = (
        ("CLE", "ATL", 98.0, 108.0, 104.0),
        ("SAC", "NOP", 102.0, 106.0, 99.0),
        ("MEM", "POR", 95.0, 110.0, 101.0),
    )
    for i, (home, away, pace, h_ortg, a_ortg) in enumerate(samples):
        engine.history.append(
            _row(
                home=home,
                away=away,
                dt=base_dt + timedelta(days=i),
                pace=pace,
                h_ortg=h_ortg,
                a_ortg=a_ortg,
            )
        )
        engine.history.append(
            _row(
                home=away,
                away=home,
                dt=base_dt + timedelta(days=i, hours=2),
                pace=pace + 1.0,
                h_ortg=a_ortg,
                a_ortg=h_ortg,
            )
        )
    kick = datetime(2026, 10, 29, 23, 0, tzinfo=timezone.utc)
    t1 = project_total_current_season(engine, "ATL", "CLE", game_date=kick)
    t2 = project_total_current_season(engine, "NOP", "SAC", game_date=kick)
    t3 = project_total_current_season(engine, "POR", "MEM", game_date=kick)
    assert all(r.get("ok") for r in (t1, t2, t3))
    totals = [float(r["total"]) for r in (t1, t2, t3)]
    assert len(set(totals)) >= 2
    assert not all(abs(x - LEAGUE_AVG_TOTAL) < 0.01 for x in totals)


def test_current_season_totals_skip_without_game_log():
    engine = V2Engine(params=V2Params(), stage=3)
    kick = datetime(2026, 10, 29, 23, 0, tzinfo=timezone.utc)
    out = project_total_current_season(engine, "BOS", "NYK", game_date=kick)
    assert out.get("ok") is False
    assert out.get("total") is None
    assert out.get("reason") == "no_season_game_log"


def test_ensure_score_engine_rebuilds_history_when_games_already_processed(monkeypatch):
    """Processed keys skip observe but projection history must still populate."""
    from sharp_scout.nba.score_model import state as state_mod

    processed = {"eid:abc"}
    engine = V2Engine(params=V2Params(), stage=3)
    games = [
        {
            "home": "CLE",
            "away": "ATL",
            "home_pts": 110.0,
            "away_pts": 105.0,
            "date": datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc),
            "season": "2026-27",
            "game_poss": 100.0,
            "event_id": "abc",
        },
        {
            "home": "ATL",
            "away": "CLE",
            "home_pts": 112.0,
            "away_pts": 109.0,
            "date": datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc),
            "season": "2026-27",
            "game_poss": 99.0,
            "event_id": "abc2",
        },
        {
            "home": "SAC",
            "away": "NOP",
            "home_pts": 115.0,
            "away_pts": 108.0,
            "date": datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc),
            "season": "2026-27",
            "game_poss": 101.0,
            "event_id": "def",
        },
        {
            "home": "NOP",
            "away": "SAC",
            "home_pts": 114.0,
            "away_pts": 111.0,
            "date": datetime(2026, 10, 27, 23, 0, tzinfo=timezone.utc),
            "season": "2026-27",
            "game_poss": 100.0,
            "event_id": "def2",
        },
    ]
    state_mod.rebuild_projection_history(engine, games)
    assert len(engine.history) == 4
    kick = datetime(2026, 10, 29, 23, 0, tzinfo=timezone.utc)
    a = project_total_current_season(engine, "ATL", "CLE", game_date=kick)
    b = project_total_current_season(engine, "NOP", "SAC", game_date=kick)
    assert a.get("ok") and b.get("ok")
    assert a["total"] != b["total"]


def test_live_scan_and_page_survive_shadow_record_failure(tmp_path, monkeypatch):
    from sharp_scout.nba.score_model.paper import (
        PAPER_PATH,
        load_paper_store,
        record_score_model_scan,
    )
    from sharp_scout.nba.score_model import totals_shadow as ts

    def _boom(*_args, **_kwargs):
        raise RuntimeError("shadow recorder failed")

    monkeypatch.setattr(ts, "maybe_record_totals_shadow_for_scan", _boom)

    store_path = tmp_path / "paper.json"
    monkeypatch.setattr("sharp_scout.nba.score_model.paper.PAPER_PATH", store_path)

    engine = V2Engine(params=V2Params(), stage=3)
    fake_pick = {"pick": "Over 220.5", "gap": 4.0, "kind": "total", "side": "over", "line": 220.5}
    monkeypatch.setattr(
        "sharp_scout.nba.score_model.pace_v1.pace_display_pick_from_snapshot",
        lambda *a, **k: fake_pick,
    )

    ev = {
        "event_id": "0123456789abcdef0123456789ab",
        "home_team": "BOS",
        "away_team": "NYK",
        "commence_time": datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc),
        "bookmakers": {
            "draftkings": {
                "key": "draftkings",
                "markets": {
                    "totals": [
                        {"side": "over", "point": 220.5, "price": -110},
                        {"side": "under", "point": 220.5, "price": -110},
                    ],
                },
            },
        },
    }
    now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    record_score_model_scan(
        [ev], engine=engine, store=load_paper_store(store_path), now=now, horizon_hours=36.0
    )
    store = load_paper_store(store_path)
    assert len(store["games"]) == 1
    assert store["games"][0]["scans"]
    assert store["games"][0].get("pace_published_pick") == fake_pick

    monkeypatch.setattr(
        "sharp_scout.site.nba_page._render_current_season_totals_tracking",
        _boom,
    )
    from sharp_scout.site.nba_page import render_nba_page_html

    html = render_nba_page_html(
        signals_payload={"ok": True, "demo": False, "signals": [], "possible_signals": []},
        ledger={"plays": []},
        report={"in_window": True, "paper_window": {}},
        analytics_head="",
        score_model_rows=[
            {
                "home": "BOS",
                "away": "NYK",
                "kickoff": ev["commence_time"],
                "margin": 1.0,
                "total": 225.0,
                "injury_total": 225.0,
                "lines": {"consensus_total": 220.5},
            }
        ],
    )
    assert "Current-season totals tracking temporarily unavailable" in html
    assert "Pace of Play model" in html
