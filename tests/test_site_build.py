"""Site build helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sharp_scout.config import ARTIFACTS_DIR
from sharp_scout.site import build as site_build
from sharp_scout.site.build import _pick_signals


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
