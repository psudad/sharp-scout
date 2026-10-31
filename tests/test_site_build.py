"""Site build helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sharp_scout.config import ARTIFACTS_DIR
from sharp_scout.site import build as site_build
from sharp_scout.site.build import (
    _extract_hybrid_leans,
    _format_play_line_suffix,
    _locked_sharp_play_keys,
    _pick_ncaaf_signals,
    _pick_signals,
    _posted_sharp_play_keys,
    _side_label,
    early_season_banner_html,
    publish_ncaaf_board_docs,
    show_early_season_banner,
)


def test_totals_play_label_omits_plus_sign():
    play = {
        "market": "totals",
        "side": "under",
        "line": 56.0,
        "price": -110,
    }
    assert _side_label(play) == "UNDER 56 (total) -110"


def test_spread_play_label_keeps_sign():
    play = {
        "market": "spreads",
        "side": "home",
        "home_team": "BUF",
        "line": -3.5,
        "price": -108,
    }
    assert _side_label(play) == "BUF -3.5 (spread) -108"


def test_early_season_banner_weeks_one_through_three_only():
    assert show_early_season_banner(1)
    assert show_early_season_banner(3)
    assert not show_early_season_banner(4)
    assert not show_early_season_banner(None)
    assert early_season_banner_html(2) != ""
    assert early_season_banner_html(5) == ""


def test_pick_signals_prefers_fresher_on_equal_game_count(tmp_path, monkeypatch):
    monkeypatch.setattr(site_build, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(site_build, "DOCS_DIR", tmp_path / "docs")
    art = tmp_path / "artifacts"
    doc = tmp_path / "docs"
    art.mkdir(parents=True)
    doc.mkdir(parents=True)
    stale = {
        "generated_at": "2026-09-03T22:00:00+00:00",
        "n_games": 80,
        "games": [{}] * 80,
        "label": "stale",
    }
    fresh = {
        "generated_at": "2026-09-04T01:38:00+00:00",
        "n_games": 80,
        "games": [{}] * 80,
        "label": "fresh",
    }
    (doc / "latest_ncaaf_signals.json").write_text(json.dumps(stale))
    (art / "latest_ncaaf_signals.json").write_text(json.dumps(fresh))
    picked = _pick_signals(("latest_ncaaf_signals.json",))
    assert picked["label"] == "fresh"


def test_pick_ncaaf_prefers_newer_artifact_over_stale_full_week_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(site_build, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(site_build, "DOCS_DIR", tmp_path / "docs")
    art = tmp_path / "artifacts"
    doc = tmp_path / "docs"
    art.mkdir(parents=True)
    doc.mkdir(parents=True)
    stale_docs = {
        "generated_at": "2026-10-27T19:56:00+00:00",
        "n_games": 56,
        "week": 9,
        "games": [{}] * 56,
        "label": "stale_week9",
    }
    fresh_art = {
        "generated_at": "2026-10-31T14:04:00+00:00",
        "n_games": 42,
        "week": 10,
        "games": [{}] * 42,
        "label": "fresh_week10",
    }
    (doc / "latest_ncaaf_signals.json").write_text(json.dumps(stale_docs))
    (art / "latest_ncaaf_signals.json").write_text(json.dumps(fresh_art))
    picked = _pick_ncaaf_signals()
    assert picked["label"] == "fresh_week10"


def test_publish_ncaaf_board_docs_writes_signals_and_plays(tmp_path, monkeypatch):
    monkeypatch.setattr(site_build, "DOCS_DIR", tmp_path / "docs")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": 10,
        "n_games": 3,
        "plays": [{"event_id": "e1", "market": "totals"}],
        "stage_picks": [],
        "ratings": [],
    }
    publish_ncaaf_board_docs(payload, docs_dir=tmp_path / "docs")
    sig = json.loads((tmp_path / "docs" / "latest_ncaaf_signals.json").read_text())
    plays = json.loads((tmp_path / "docs" / "ncaaf_plays.json").read_text())
    assert sig["week"] == 10
    assert len(plays) == 1


def test_pick_signals_prefers_fullest_board_over_partial_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(site_build, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(site_build, "DOCS_DIR", tmp_path / "docs")
    art = tmp_path / "artifacts"
    doc = tmp_path / "docs"
    art.mkdir(parents=True)
    doc.mkdir(parents=True)
    full_docs = {
        "generated_at": "2026-09-03T22:00:00+00:00",
        "n_games": 90,
        "games": [{}] * 90,
        "label": "full_docs",
    }
    partial_art = {
        "generated_at": "2026-09-04T01:38:00+00:00",
        "n_games": 80,
        "games": [{}] * 80,
        "label": "partial_art",
    }
    (doc / "latest_ncaaf_signals.json").write_text(json.dumps(full_docs))
    (art / "latest_ncaaf_signals.json").write_text(json.dumps(partial_art))
    picked = _pick_signals(("latest_ncaaf_signals.json",))
    assert picked["label"] == "full_docs"


def test_locked_sharp_play_keys_include_graded_wins():
    plays = [
        {
            "event_id": "ev1",
            "market": "totals",
            "side": "over",
            "status": "win",
        },
        {
            "event_id": "ev2",
            "market": "spreads",
            "side": "home",
            "status": "quarantined",
        },
    ]
    keys = _locked_sharp_play_keys(plays)
    assert keys == {("ev1", "total", "over")}


def test_posted_sharp_play_keys_exclude_quarantined():
    plays = [
        {
            "event_id": "ev1",
            "market": "spreads",
            "side": "home",
            "status": "quarantined",
        },
        {
            "event_id": "ev2",
            "market": "spreads",
            "side": "away",
            "status": "pending",
        },
    ]
    keys = _posted_sharp_play_keys(plays)
    assert keys == {("ev2", "spread", "away")}


def test_quarantined_ledger_play_stays_model_lean_not_sharp_play():
    stage_cards = [
        {
            "event_id": "ev1",
            "home_team": "Florida State",
            "away_team": "SMU",
            "market": "spread",
            "kickoff": "2026-09-07T23:30:00+00:00",
            "picks": {
                "hybrid": {
                    "available": True,
                    "side": "home",
                    "team": "Florida State",
                    "reason": "Validated play — RLM toward home",
                }
            },
        }
    ]
    ledger_plays = [
        {
            "event_id": "ev1",
            "market": "spreads",
            "side": "home",
            "status": "quarantined",
        }
    ]
    leans = _extract_hybrid_leans(stage_cards, ledger_plays=ledger_plays)
    assert len(leans) == 1
    assert leans[0]["is_sharp_play"] is False
    assert leans[0]["kind"] == "model"
