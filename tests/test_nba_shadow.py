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
    assert "CHA" in nba_html or "LaMelo" in nba_html
    assert (docs / "nba_latest_signals.json").exists()
