"""Ledger settlement + record tests."""

from __future__ import annotations

import json
from pathlib import Path

from sharp_scout.ledger.tracker import (
    append_signals,
    compute_record,
    empty_ledger,
    save_ledger,
    settle_from_scores,
    settle_play,
)
from sharp_scout.site.build import build_site


def test_settle_spread_home_cover(tmp_path: Path):
    play = {
        "market": "spreads",
        "side": "home",
        "line": -3.0,
        "price": -110,
        "units": 1.0,
        "status": "pending",
    }
    settle_play(play, home_score=27, away_score=20)
    assert play["status"] == "win"
    assert play["pnl_units"] > 0


def test_settle_total_under(tmp_path: Path):
    play = {
        "market": "totals",
        "side": "under",
        "line": 47.5,
        "price": -110,
        "units": 1.5,
        "status": "pending",
    }
    settle_play(play, home_score=20, away_score=17)
    assert play["status"] == "win"


def test_ledger_append_dedupe(tmp_path: Path):
    path = tmp_path / "ledger.json"
    save_ledger(empty_ledger(), path)
    sig = {
        "event_id": "e1",
        "away_team": "KC",
        "home_team": "BUF",
        "market": "totals",
        "side": "under",
        "line": 47.5,
        "book": "draftkings",
        "price": -110,
        "edge": 0.05,
        "p_true": 0.55,
        "tier": "play",
        "filter_passed": True,
        "rationale": "test",
    }
    append_signals([sig], path=path, season=2025, week=1)
    append_signals([sig], path=path, season=2025, week=1)
    data = json.loads(path.read_text())
    assert len(data["plays"]) == 1


def test_ledger_replaces_pending_same_side_different_book(tmp_path: Path):
    path = tmp_path / "ledger.json"
    save_ledger(empty_ledger(), path)
    base = {
        "event_id": "e1",
        "away_team": "MIN",
        "home_team": "NYG",
        "market": "spreads",
        "side": "home",
        "price": -110,
        "edge": 0.05,
        "p_true": 0.55,
        "tier": "play",
        "filter_passed": True,
        "rationale": "first",
    }
    append_signals([{**base, "line": 1.5, "book": "draftkings"}], path=path)
    append_signals([{**base, "line": 2.5, "book": "fanduel", "edge": 0.08, "rationale": "better"}], path=path)
    data = json.loads(path.read_text())
    assert len(data["plays"]) == 1
    assert data["plays"][0]["book"] == "fanduel"
    assert data["plays"][0]["line"] == 2.5
    assert data["plays"][0]["edge"] == 0.08


def test_record_and_site(tmp_path: Path, monkeypatch):
    path = tmp_path / "ledger.json"
    save_ledger(empty_ledger(), path)
    sigs = [
        {
            "event_id": "e1",
            "away_team": "KC",
            "home_team": "BUF",
            "market": "totals",
            "side": "under",
            "line": 47.5,
            "book": "dk",
            "price": -110,
            "edge": 0.04,
            "p_true": 0.54,
            "tier": "play",
            "filter_passed": True,
            "rationale": "edge",
        }
    ]
    append_signals(sigs, path=path, season=2025, week=1)
    settle_from_scores(
        [{"away_team": "KC", "home_team": "BUF", "away_score": 20, "home_score": 17}],
        path=path,
    )
    # Point ledger loader at tmp by monkeypatching path used in build
    import sharp_scout.ledger.tracker as tr
    import sharp_scout.site.build as sb

    monkeypatch.setattr(tr, "LEDGER_PATH", path)
    monkeypatch.setattr(sb, "DOCS_DIR", tmp_path / "docs")
    # build_site imports load_ledger from tracker — patch module attr so NCAAF
    # path= kwargs (and NFL default) both resolve to the tmp ledger.
    monkeypatch.setattr(
        sb,
        "load_ledger",
        lambda path=None, nfl_path=path: tr.load_ledger(path if path is not None else nfl_path),
    )
    monkeypatch.setattr(
        sb,
        "compute_record",
        lambda ledger=None, path=None, nfl_path=path: tr.compute_record(
            ledger if ledger is not None else tr.load_ledger(path if path is not None else nfl_path)
        ),
    )

    out = build_site(docs_dir=tmp_path / "docs")
    assert (out / "index.html").exists()
    assert (out / "ledger.json").exists()
    rec = compute_record(tr.load_ledger(path))
    assert rec["wins"] == 1
    assert rec["record"] == "1-0"
