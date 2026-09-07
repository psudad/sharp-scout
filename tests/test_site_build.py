"""Site build helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sharp_scout.config import ARTIFACTS_DIR
from sharp_scout.site import build as site_build
from sharp_scout.site.build import _extract_hybrid_leans, _pick_signals, _posted_sharp_play_keys


def test_pick_signals_prefers_fresher_artifacts_on_equal_game_count(tmp_path, monkeypatch):
    monkeypatch.setattr(site_build, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(site_build, "DOCS_DIR", tmp_path / "docs")
    art = tmp_path / "artifacts"
    doc = tmp_path / "docs"
    art.mkdir(parents=True)
    doc.mkdir(parents=True)
    stale = {
        "generated_at": "2026-09-03T22:00:00+00:00",
        "n_games": 90,
        "games": [{}] * 90,
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
