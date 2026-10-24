"""NBA shadow pipeline tests (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from sharp_scout.nba.demo import mock_nba_events
from sharp_scout.nba.game_lines import discover_game_line_edges
from sharp_scout.nba.pipeline import run_nba_shadow
from sharp_scout.nba.props import discover_prop_edges
from sharp_scout.nba.projections import default_demo_rates
from sharp_scout.site.build import build_site
from sharp_scout.site.nba_page import NO_LIVE_SCAN_MESSAGE


def test_game_line_scanner_finds_retail_edge():
    ev = mock_nba_events()[0]
    edges = discover_game_line_edges(ev)
    assert edges, "expected at least one game-line edge in demo fixture"
    assert all(e.edge >= 0.02 for e in edges)
    assert all(e.book in ("fanduel", "draftkings") for e in edges)


def test_prop_scanner_respects_over_margin_and_consensus():
    ev = mock_nba_events()[0]
    rates = default_demo_rates()
    edges = discover_prop_edges(ev, rates=rates)
    assert edges
    assert any(e.market.startswith("player_") for e in edges)


def test_run_nba_shadow_demo_writes_private_paths(tmp_path, monkeypatch):
    from sharp_scout.nba import paths as nba_paths

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(nba_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(nba_paths, "NBA_LEDGER_PATH", shadow / "nba_ledger.json")
    monkeypatch.setattr(nba_paths, "NBA_LATEST_SIGNALS_PATH", shadow / "nba_latest_signals.json")
    monkeypatch.setattr(nba_paths, "NBA_LINE_HISTORY_PATH", shadow / "nba_line_history.json")
    monkeypatch.setattr(nba_paths, "NBA_REPORT_PATH", shadow / "nba_paper_report.json")
    monkeypatch.setattr(nba_paths, "NBA_ARTIFACT_DIR", tmp_path / "artifacts")

    payload = run_nba_shadow(demo=True, append_ledger=True)
    assert payload["ok"]
    assert payload["n_signals"] >= 1
    assert (shadow / "nba_latest_signals.json").exists()
    ledger = json.loads((shadow / "nba_ledger.json").read_text())
    assert ledger["mode"] == "shadow"
    for play in ledger["plays"]:
        assert play.get("sport") == "nba"


def test_football_pages_have_no_nba_shadow_content(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.chdir(tmp_path)
    build_site(docs_dir=docs, signals_path=Path("/workspace/artifacts/latest_signals.json"))
    html = (docs / "index.html").read_text() if (docs / "index.html").exists() else ""
    board = (docs / "board.html").read_text() if (docs / "board.html").exists() else ""
    combined = html + board
    assert "nba_shadow" not in combined.lower()
    assert "basketball_nba" not in combined


def test_nba_public_page_isolated(tmp_path, monkeypatch):
    from sharp_scout.nba import paths as nba_paths

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(nba_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(nba_paths, "NBA_LEDGER_PATH", shadow / "nba_ledger.json")
    monkeypatch.setattr(nba_paths, "NBA_LATEST_SIGNALS_PATH", shadow / "nba_latest_signals.json")
    monkeypatch.setattr(nba_paths, "NBA_REPORT_PATH", shadow / "nba_paper_report.json")
    monkeypatch.setattr(nba_paths, "NBA_LINE_HISTORY_PATH", shadow / "nba_line_history.json")
    monkeypatch.setattr(nba_paths, "NBA_ARTIFACT_DIR", tmp_path / "artifacts")

    run_nba_shadow(demo=True, append_ledger=True)
    docs = tmp_path / "docs"
    build_site(docs_dir=docs, signals_path=Path("/workspace/artifacts/latest_signals.json"))

    nba_html = (docs / "nba.html").read_text()
    nba_body = nba_html.split("<script", 1)[0]
    assert "This is just for testing." in nba_html
    assert "lp-card" not in nba_body
    assert 'class="lp-add"' not in nba_body
    assert "+ Add to my card" not in nba_body
    assert NO_LIVE_SCAN_MESSAGE in nba_html
    assert "CHA" not in nba_body
    assert "LaMelo" not in nba_body
    pub_signals = json.loads((docs / "nba_latest_signals.json").read_text())
    assert pub_signals.get("signals") == []
    assert pub_signals.get("demo") is False
    pub_ledger = json.loads((docs / "nba_ledger.json").read_text())
    assert pub_ledger.get("plays") == []


def test_nba_public_page_shows_live_scan_only(tmp_path, monkeypatch):
    from sharp_scout.nba import paths as nba_paths
    from sharp_scout.site.nba_page import NO_LIVE_SCAN_MESSAGE, build_nba_page

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(nba_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(nba_paths, "NBA_LEDGER_PATH", shadow / "nba_ledger.json")
    monkeypatch.setattr(nba_paths, "NBA_LATEST_SIGNALS_PATH", shadow / "nba_latest_signals.json")
    monkeypatch.setattr(nba_paths, "NBA_REPORT_PATH", shadow / "nba_paper_report.json")

    live_signals = {
        "ok": True,
        "demo": False,
        "generated_at": "2026-10-24T18:00:00+00:00",
        "n_events": 1,
        "n_signals": 1,
        "signals": [
            {
                "event_id": "live-ev-1",
                "play_type": "side",
                "kickoff": "2026-10-25T00:00:00+00:00",
                "away_team": "BOS",
                "home_team": "NYK",
                "market": "spreads",
                "side": "away",
                "line": 4.5,
                "book": "fanduel",
                "price": -110,
                "units": 1.0,
                "edge": 0.03,
                "p_true": 0.54,
            }
        ],
    }
    (shadow / "nba_latest_signals.json").write_text(json.dumps(live_signals) + "\n")
    (shadow / "nba_ledger.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-10-24T18:00:00+00:00",
                "sport": "nba",
                "mode": "shadow",
                "plays": [
                    {
                        "event_id": "live-ev-1",
                        "play_type": "side",
                        "market": "spreads",
                        "status": "paper",
                    }
                ],
            }
        )
        + "\n"
    )

    docs = tmp_path / "docs"
    build_nba_page(docs_dir=docs)
    html = (docs / "nba.html").read_text()
    assert NO_LIVE_SCAN_MESSAGE not in html
    assert "BOS" in html
    exported = json.loads((docs / "nba_latest_signals.json").read_text())
    assert len(exported["signals"]) == 1
    assert exported.get("possible_signals") == []


def test_nba_page_picks_and_possible_sections(tmp_path, monkeypatch):
    from sharp_scout.nba import paths as nba_paths
    from sharp_scout.site.nba_page import build_nba_page

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(nba_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(nba_paths, "NBA_LEDGER_PATH", shadow / "nba_ledger.json")
    monkeypatch.setattr(nba_paths, "NBA_LATEST_SIGNALS_PATH", shadow / "nba_latest_signals.json")
    monkeypatch.setattr(nba_paths, "NBA_REPORT_PATH", shadow / "nba_paper_report.json")

    payload = {
        "ok": True,
        "demo": False,
        "generated_at": "2026-10-24T20:00:00+00:00",
        "n_events": 1,
        "n_signals": 1,
        "signals": [
            {
                "event_id": "live-ev-1",
                "play_type": "side",
                "kickoff": "2026-10-25T00:00:00+00:00",
                "away_team": "BOS",
                "home_team": "NYK",
                "market": "spreads",
                "side": "away",
                "line": 4.5,
                "book": "fanduel",
                "price": -110,
                "units": 1.0,
                "edge": 0.03,
                "p_true": 0.54,
                "filter_passed": True,
            }
        ],
        "n_possible": 1,
        "possible_signals": [
            {
                "event_id": "live-ev-1",
                "play_type": "side",
                "kickoff": "2026-10-25T00:00:00+00:00",
                "away_team": "BOS",
                "home_team": "NYK",
                "market": "totals",
                "side": "over",
                "line": 220.5,
                "book": "draftkings",
                "price": -105,
                "units": 0,
                "edge": 0.012,
                "p_true": 0.52,
                "reject_reason": "EV below 2.0% floor",
                "pick_class": "possible",
                "display_only": True,
            }
        ],
    }
    (shadow / "nba_latest_signals.json").write_text(json.dumps(payload) + "\n")

    docs = tmp_path / "docs"
    build_nba_page(docs_dir=docs)
    html = (docs / "nba.html").read_text()
    assert "Game lines" in html
    assert "Possible picks" in html
    assert "After more testing, we'd pick:" in html
    assert "EV below 2.0% floor" in html
    assert "display only" in html
    exported = json.loads((docs / "nba_latest_signals.json").read_text())
    assert len(exported["possible_signals"]) == 1
    assert exported["possible_signals"][0]["units"] == 0


def test_demo_shadow_populates_possible_without_publishing(tmp_path, monkeypatch):
    from sharp_scout.nba import paths as nba_paths

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(nba_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(nba_paths, "NBA_LEDGER_PATH", shadow / "nba_ledger.json")
    monkeypatch.setattr(nba_paths, "NBA_LATEST_SIGNALS_PATH", shadow / "nba_latest_signals.json")
    monkeypatch.setattr(nba_paths, "NBA_LINE_HISTORY_PATH", shadow / "nba_line_history.json")
    monkeypatch.setattr(nba_paths, "NBA_REPORT_PATH", shadow / "nba_paper_report.json")
    monkeypatch.setattr(nba_paths, "NBA_ARTIFACT_DIR", tmp_path / "artifacts")

    payload = run_nba_shadow(demo=True, append_ledger=False)
    assert "possible_signals" in payload
    shadow_payload = json.loads((shadow / "nba_latest_signals.json").read_text())
    assert shadow_payload.get("demo") is True
    assert isinstance(shadow_payload.get("possible_signals"), list)


def test_cap_props_per_game_picks_first_then_possible():
    from sharp_scout.nba.possible import cap_props_per_game

    eid = "game-1"
    picks = [
        {
            "event_id": eid,
            "play_type": "prop",
            "player_name": "A",
            "market": "player_points",
            "side": "over",
            "line": 20.5,
            "edge": 0.05,
        },
        {
            "event_id": eid,
            "play_type": "prop",
            "player_name": "B",
            "market": "player_rebounds",
            "side": "over",
            "line": 5.5,
            "edge": 0.04,
        },
        {
            "event_id": eid,
            "play_type": "prop",
            "player_name": "C",
            "market": "player_assists",
            "side": "over",
            "line": 6.5,
            "edge": 0.03,
        },
    ]
    possible = [
        {
            "event_id": eid,
            "play_type": "prop",
            "player_name": "D",
            "market": "player_threes",
            "side": "over",
            "line": 2.5,
            "edge": 0.09,
        },
        {
            "event_id": eid,
            "play_type": "prop",
            "player_name": "E",
            "market": "player_points",
            "side": "under",
            "line": 25.5,
            "edge": 0.08,
        },
    ]
    kept_picks, kept_possible = cap_props_per_game(
        picks + [{"event_id": eid, "play_type": "side", "market": "spreads", "side": "home", "edge": 0.1}],
        possible,
        max_per_game=5,
    )
    prop_picks = [p for p in kept_picks if p.get("play_type") == "prop"]
    assert len(prop_picks) == 3
    assert len([p for p in kept_possible if p.get("play_type") == "prop"]) == 2
    assert prop_picks[0]["player_name"] == "A"
    names = {p["player_name"] for p in kept_possible if p.get("play_type") == "prop"}
    assert names == {"D", "E"}


def test_cap_props_per_game_trims_excess_picks():
    from sharp_scout.nba.possible import cap_props_per_game

    eid = "game-2"
    picks = [
        {
            "event_id": eid,
            "play_type": "prop",
            "player_name": f"P{i}",
            "market": "player_points",
            "side": "over",
            "line": 20.5 + i,
            "edge": 0.01 * (10 - i),
        }
        for i in range(7)
    ]
    kept_picks, kept_possible = cap_props_per_game(picks, [], max_per_game=5)
    assert len([p for p in kept_picks if p.get("play_type") == "prop"]) == 5
    assert kept_possible == []


def test_symmetric_prop_consensus_has_near_zero_edge():
    from sharp_scout.nba.props import scan_prop_opportunities

    ev = {
        "event_id": "sym-test",
        "home_team": "AAA",
        "away_team": "BBB",
        "bookmakers": {
            "fanduel": {
                "markets": {
                    "player_points": [
                        {
                            "side": "over",
                            "description": "Test Player",
                            "price": -110,
                            "point": 20.5,
                        },
                        {
                            "side": "under",
                            "description": "Test Player",
                            "price": -110,
                            "point": 20.5,
                        },
                    ]
                }
            },
            "draftkings": {
                "markets": {
                    "player_points": [
                        {
                            "side": "over",
                            "description": "Test Player",
                            "price": -110,
                            "point": 20.5,
                        },
                        {
                            "side": "under",
                            "description": "Test Player",
                            "price": -110,
                            "point": 20.5,
                        },
                    ]
                }
            },
            "betmgm": {
                "markets": {
                    "player_points": [
                        {
                            "side": "over",
                            "description": "Test Player",
                            "price": -110,
                            "point": 20.5,
                        },
                        {
                            "side": "under",
                            "description": "Test Player",
                            "price": -110,
                            "point": 20.5,
                        },
                    ]
                }
            },
            "espnbet": {
                "markets": {
                    "player_points": [
                        {
                            "side": "over",
                            "description": "Test Player",
                            "price": -110,
                            "point": 20.5,
                        },
                        {
                            "side": "under",
                            "description": "Test Player",
                            "price": -110,
                            "point": 20.5,
                        },
                    ]
                }
            },
        },
    }
    from sharp_scout.nba.props import _consensus_only_edge

    for side in ("over", "under"):
        p_true, edge, skip = _consensus_only_edge(
            ev,
            market="player_points",
            player_name="Test Player",
            line=20.5,
            side=side,
            book_key="fanduel",
            price=-110.0,
        )
        assert skip is None, side
        assert p_true is not None
        assert edge is not None
        assert edge <= 0, side

    opps = scan_prop_opportunities(ev, rates={}, file_rate_keys=set())
    assert not opps, "symmetric -110/-110 across books should not emit +EV rows"


def test_merge_open_ledger_picks_restores_picks_list():
    from datetime import datetime, timedelta, timezone

    from sharp_scout.nba.ledger import merge_open_ledger_picks

    kick = (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()
    ledger = {
        "plays": [
            {
                "id": "abc",
                "status": "paper",
                "event_id": "e1",
                "kickoff": kick,
                "away_team": "A",
                "home_team": "B",
                "play_type": "side",
                "market": "totals",
                "side": "under",
                "line": 220.5,
                "book": "fanduel",
                "price": -110,
                "units": 1.0,
                "edge": 0.04,
            }
        ]
    }
    possible = [
        {
            "event_id": "e1",
            "play_type": "side",
            "market": "totals",
            "side": "under",
            "line": 220.5,
            "book": "fanduel",
            "edge": 0.04,
            "pick_class": "possible",
        }
    ]
    picks, poss = merge_open_ledger_picks([], possible, ledger, live_scan=True)
    assert len(picks) == 1
    assert picks[0].get("from_ledger") is True
    assert poss == []


def test_merge_open_ledger_skips_demo_and_past_kickoff():
    from datetime import datetime, timedelta, timezone

    from sharp_scout.nba.ledger import merge_open_ledger_picks
    from sharp_scout.site.nba_page import public_nba_signals

    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    ledger = {
        "plays": [
            {
                "id": "demo",
                "status": "paper",
                "event_id": "demo-nba-cha-mia",
                "kickoff": future,
                "play_type": "side",
                "market": "spreads",
                "side": "away",
                "line": 5.5,
                "book": "fanduel",
                "price": -110,
                "units": 1.0,
            },
            {
                "id": "old",
                "status": "paper",
                "event_id": "live-1",
                "kickoff": past,
                "play_type": "side",
                "market": "totals",
                "side": "over",
                "line": 220.5,
                "book": "fanduel",
                "price": -110,
                "units": 1.0,
            },
        ]
    }
    picks, _ = merge_open_ledger_picks([], [], ledger, live_scan=True)
    assert picks == []

    payload = {
        "ok": True,
        "demo": False,
        "signals": [
            {
                "event_id": "demo-nba-cha-mia",
                "play_type": "side",
                "market": "spreads",
                "side": "away",
                "line": 5.5,
            }
        ],
        "possible_signals": [],
    }
    pub = public_nba_signals(payload)
    assert pub["signals"] == []


def test_run_nba_shadow_includes_prop_diagnostics(tmp_path, monkeypatch):
    from sharp_scout.nba import paths as nba_paths

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(nba_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(nba_paths, "NBA_LEDGER_PATH", shadow / "nba_ledger.json")
    monkeypatch.setattr(nba_paths, "NBA_LATEST_SIGNALS_PATH", shadow / "nba_latest_signals.json")
    monkeypatch.setattr(nba_paths, "NBA_LINE_HISTORY_PATH", shadow / "nba_line_history.json")
    monkeypatch.setattr(nba_paths, "NBA_REPORT_PATH", shadow / "nba_paper_report.json")
    monkeypatch.setattr(nba_paths, "NBA_ARTIFACT_DIR", tmp_path / "artifacts")

    payload = run_nba_shadow(demo=True, append_ledger=False)
    diag = payload.get("prop_diagnostics") or {}
    assert "lines_scanned" in diag
    assert diag.get("lines_scanned", 0) >= 1


def test_nba_config_prop_defaults():
    from sharp_scout.config import Settings

    s = Settings()
    assert s.nba_max_prop_events_per_run == 10
    assert s.nba_prop_regions == "us,us2"
    assert s.nba_max_props_per_game == 5


def test_events_in_horizon_excludes_started_and_far_future():
    from datetime import datetime, timedelta, timezone

    from sharp_scout.nba.pipeline import _events_in_horizon

    now = datetime.now(timezone.utc)
    events = [
        {"event_id": "past", "commence_time": now - timedelta(hours=1)},
        {"event_id": "live", "commence_time": now},
        {"event_id": "soon", "commence_time": now + timedelta(hours=12)},
        {"event_id": "xmas", "commence_time": now + timedelta(days=60)},
    ]
    in_window = _events_in_horizon(events, hours=36.0)
    ids = {e["event_id"] for e in in_window}
    assert ids == {"soon"}


def test_append_nba_signals_refuses_past_kickoff(tmp_path):
    from datetime import datetime, timedelta, timezone

    from sharp_scout.nba.ledger import append_nba_signals, load_nba_ledger

    ledger_path = tmp_path / "nba_ledger.json"
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    result = append_nba_signals(
        [
            {
                "event_id": "late-log",
                "kickoff": past,
                "away_team": "MIA",
                "home_team": "CHA",
                "market": "h2h",
                "side": "away",
                "price": 138,
                "units": 1.5,
                "edge": 0.1,
                "p_true": 0.5,
                "p_mkt": 0.5,
            }
        ],
        path=ledger_path,
    )
    assert result["added"] == 0
    assert load_nba_ledger(ledger_path)["plays"] == []


def test_merge_open_ledger_skips_outside_horizon():
    from datetime import datetime, timedelta, timezone

    from sharp_scout.nba.ledger import merge_open_ledger_picks

    future = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
    ledger = {
        "plays": [
            {
                "id": "xmas",
                "status": "paper",
                "event_id": "christmas",
                "kickoff": future,
                "play_type": "side",
                "market": "h2h",
                "side": "home",
                "line": None,
                "book": "draftkings",
                "price": -185,
                "units": 1.5,
            }
        ]
    }
    picks, _ = merge_open_ledger_picks([], [], ledger, live_scan=True)
    assert picks == []
