"""NCAAF high-EV totals shadow ledger (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from sharp_scout.ncaaf.shadow import paths as shadow_paths
from sharp_scout.ncaaf.shadow.capture import record_from_pipeline
from sharp_scout.ncaaf.shadow.ledger import load_ledger, play_key
from sharp_scout.ncaaf.shadow.report import build_summary, write_summary_and_report
from sharp_scout.site.build import build_site


def _sample_totals_signal(**overrides):
    base = {
        "event_id": "evt1",
        "away_team": "AAA",
        "home_team": "BBB",
        "kickoff": "2027-10-24T20:00:00+00:00",
        "market": "totals",
        "side": "over",
        "line": 52.5,
        "book": "draftkings",
        "price": -105.0,
        "edge": 0.14,
        "p_fair": 0.55,
        "sharp_price": -110.0,
        "sharp_book": "pinnacle",
        "flags": {"rlm": True, "money_split": False, "steam": False},
        "filter_passed": False,
    }
    base.update(overrides)
    return base


def test_record_dedupes_by_event_side_and_updates_snapshot(tmp_path, monkeypatch):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(shadow_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(shadow_paths, "LEDGER_PATH", shadow / "ledger.json")
    monkeypatch.setattr(shadow_paths, "SUMMARY_PATH", shadow / "summary.json")
    monkeypatch.setattr(shadow_paths, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(shadow_paths, "MARKDOWN_REPORT_PATH", tmp_path / "reports" / "r.md")

    s1 = _sample_totals_signal(edge=0.14, price=-105)
    record_from_pipeline([s1], signals_payload={"generated_at": "2027-10-24T11:00:00+00:00"}, season=2026, week=8)
    s2 = _sample_totals_signal(edge=0.15, price=-100, book="fanduel")
    record_from_pipeline([s2], signals_payload={"generated_at": "2027-10-24T12:00:00+00:00"}, season=2026, week=8)

    ledger = load_ledger(shadow / "ledger.json")
    assert len(ledger["plays"]) == 1
    row = ledger["plays"][0]
    assert row["bucket"] == "ev_12_16"
    assert row["first_seen"]["edge"] == 0.14
    assert row["edge"] == 0.15
    assert row["book"] == "fanduel"


def test_high_ev_buckets_split_at_16_percent(tmp_path, monkeypatch):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(shadow_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(shadow_paths, "LEDGER_PATH", shadow / "ledger.json")

    over = _sample_totals_signal(side="over", edge=0.17, event_id="e1")
    under = _sample_totals_signal(side="under", edge=0.13, event_id="e1")
    record_from_pipeline([over, under], signals_payload={"signals": [over, under]})

    ledger = load_ledger(shadow / "ledger.json")
    keys = {play_key(p["event_id"], p["side"], bucket=p["bucket"]) for p in ledger["plays"]}
    assert "e1|totals|over|ev_16_plus" in keys
    assert "e1|totals|under|ev_12_16" in keys


def test_public_site_excludes_ncaaf_totals_shadow(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.chdir(tmp_path)
    build_site(docs_dir=docs, signals_path=Path("/workspace/artifacts/latest_signals.json"))
    combined = ""
    for name in ("index.html", "board.html", "ncaaf.html"):
        p = docs / name
        if p.exists():
            combined += p.read_text().lower()
    assert "ncaaf_totals_shadow" not in combined
    assert "ncaaf_totals_high_ev" not in combined


def test_summary_written(tmp_path, monkeypatch):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(shadow_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(shadow_paths, "LEDGER_PATH", shadow / "ledger.json")
    monkeypatch.setattr(shadow_paths, "SUMMARY_PATH", shadow / "summary.json")
    monkeypatch.setattr(shadow_paths, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(shadow_paths, "MARKDOWN_REPORT_PATH", tmp_path / "reports" / "r.md")

    record_from_pipeline([_sample_totals_signal()], signals_payload={"signals": []})
    write_summary_and_report()
    summary = json.loads((shadow / "summary.json").read_text())
    assert summary["overall_high_ev"]["n"] >= 1
