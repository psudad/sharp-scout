"""NCAAF docs/ publish safeguard — skip-pbp / demo / low team count must not overwrite docs/."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from sharp_scout.config import ARTIFACTS_DIR, DATA_DIR
from sharp_scout.ncaaf.publish_gate import (
    decide_ncaaf_publish,
    is_ncaaf_payload_publishable,
    stamp_publishable,
)
from sharp_scout.qa.gate import MIN_RATED_TEAMS_NCAAF
from sharp_scout.site import build as site_build
from sharp_scout.site.build import publish_ncaaf_board_docs
from sharp_scout.utils import teams as teams_mod


@pytest.fixture(autouse=True)
def _reset_learned_mascots():
    """Pipeline integration tests call register_mascots; do not leak into other modules."""
    saved = set(teams_mod._LEARNED_MASCOTS)
    yield
    teams_mod._LEARNED_MASCOTS.clear()
    teams_mod._LEARNED_MASCOTS.update(saved)


def _good_ratings(n: int = MIN_RATED_TEAMS_NCAAF) -> list[dict]:
    return [{"team": f"T{i:03d}", "power": float(i) * 0.01} for i in range(n)]


def _payload(*, n_teams: int = 20, demo: bool = False, skip_pbp: bool = True) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sport": "ncaaf",
        "demo": demo,
        "skip_pbp": skip_pbp,
        "n_games": 40,
        "games": [{}] * 40,
        "ratings": _good_ratings(n_teams) if n_teams else [],
        "plays": [{"event_id": "real1", "market": "spreads", "filter_passed": True}],
        "stage_picks": [],
    }


def test_decide_blocks_skip_pbp_and_demo():
    assert not decide_ncaaf_publish(_payload(skip_pbp=True), skip_pbp=True).publishable
    assert not decide_ncaaf_publish(_payload(demo=True, skip_pbp=False), skip_pbp=False).publishable


def test_decide_blocks_low_team_count():
    d = decide_ncaaf_publish(
        _payload(n_teams=20, skip_pbp=False),
        skip_pbp=False,
    )
    assert not d.publishable
    assert d.n_rated_teams == 20


def test_decide_allows_full_ratings_without_skip_pbp():
    d = decide_ncaaf_publish(
        _payload(n_teams=MIN_RATED_TEAMS_NCAAF, skip_pbp=False),
        skip_pbp=False,
    )
    assert d.publishable


def test_decide_allows_publish_when_other_layer1_would_block_game_count():
    """Low game count blocks QA deploy but must not block NCAAF docs publish."""
    payload = _payload(n_teams=MIN_RATED_TEAMS_NCAAF, skip_pbp=False, demo=False)
    payload["n_games"] = 1
    payload["games"] = [{}]
    assert decide_ncaaf_publish(payload, skip_pbp=False).publishable


def test_publish_ncaaf_board_docs_leaves_existing_docs_byte_identical(tmp_path, caplog):
    caplog.set_level(logging.ERROR)
    docs = tmp_path / "docs"
    docs.mkdir()
    existing = {
        "generated_at": "2026-10-01T12:00:00+00:00",
        "week": 6,
        "n_games": 50,
        "games": [{}] * 50,
        "plays": [],
        "ratings": _good_ratings(90),
        "publishable": True,
    }
    blob = json.dumps(existing, indent=2) + "\n"
    (docs / "latest_ncaaf_signals.json").write_bytes(blob.encode())

    bad = _payload(n_teams=20, skip_pbp=True)
    stamp_publishable(bad, decide_ncaaf_publish(bad, skip_pbp=True))

    publish_ncaaf_board_docs(bad, docs_dir=docs)
    assert (docs / "latest_ncaaf_signals.json").read_bytes() == blob.encode()
    assert any("NCAAF publish BLOCKED" in r.message for r in caplog.records)


def test_publish_ncaaf_board_docs_writes_when_publishable(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    existing = {
        "generated_at": "2026-10-01T12:00:00+00:00",
        "week": 6,
        "plays": [],
        "ratings": [],
    }
    (docs / "latest_ncaaf_signals.json").write_text(json.dumps(existing))

    good = _payload(n_teams=MIN_RATED_TEAMS_NCAAF, skip_pbp=False, demo=False)
    good["week"] = 10
    stamp_publishable(good, decide_ncaaf_publish(good, skip_pbp=False))
    publish_ncaaf_board_docs(good, docs_dir=docs)
    written = json.loads((docs / "latest_ncaaf_signals.json").read_text())
    assert written["week"] == 10
    assert len(written["ratings"]) == MIN_RATED_TEAMS_NCAAF


def test_demo_mode_does_not_publish(tmp_path, caplog):
    caplog.set_level(logging.ERROR)
    docs = tmp_path / "docs"
    docs.mkdir()
    prior = json.dumps({"generated_at": "2026-01-01T00:00:00+00:00", "week": 1}) + "\n"
    (docs / "latest_ncaaf_signals.json").write_bytes(prior.encode())

    demo_payload = _payload(n_teams=MIN_RATED_TEAMS_NCAAF, demo=True, skip_pbp=True)
    stamp_publishable(demo_payload, decide_ncaaf_publish(demo_payload, skip_pbp=True))
    publish_ncaaf_board_docs(demo_payload, docs_dir=docs)
    assert (docs / "latest_ncaaf_signals.json").read_bytes() == prior.encode()


def test_pick_ncaaf_ignores_unpublishable_newer_artifact(tmp_path, monkeypatch):
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
        "label": "good_docs",
        "publishable": True,
    }
    bad_art = {
        "generated_at": "2026-10-31T14:04:00+00:00",
        "n_games": 42,
        "week": 10,
        "games": [{}] * 42,
        "label": "bad_skip_pbp",
        "publishable": False,
        "publish_block_reason": "skip_pbp",
    }
    (doc / "latest_ncaaf_signals.json").write_text(json.dumps(stale_docs))
    (art / "latest_ncaaf_signals.json").write_text(json.dumps(bad_art))

    from sharp_scout.site.build import _pick_ncaaf_signals

    picked = _pick_ncaaf_signals()
    assert picked["label"] == "good_docs"


def test_is_ncaaf_payload_publishable_defaults_true_for_legacy():
    assert is_ncaaf_payload_publishable({"n_games": 1, "games": [{}]})
    assert not is_ncaaf_payload_publishable({"publishable": False})


def test_pipeline_skip_pbp_blocks_docs_publish(tmp_path, monkeypatch):
    """Integration: skip-pbp run must not overwrite docs/latest_ncaaf_signals.json."""
    monkeypatch.setattr("sharp_scout.ncaaf.pipeline.ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr("sharp_scout.ncaaf.pipeline.DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(site_build, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(site_build, "DOCS_DIR", tmp_path / "docs")
    (tmp_path / "artifacts").mkdir(parents=True)
    (tmp_path / "data").mkdir(parents=True)
    docs = tmp_path / "docs"
    docs.mkdir()
    good_blob = json.dumps(
        {
            "generated_at": "2026-09-01T00:00:00+00:00",
            "week": 1,
            "n_games": 10,
            "games": [{}] * 10,
            "ratings": _good_ratings(90),
            "plays": [],
        },
        indent=2,
    ) + "\n"
    (docs / "latest_ncaaf_signals.json").write_bytes(good_blob.encode())
    (tmp_path / "data" / "ncaaf_ledger.json").write_text('{"plays": []}')

    from sharp_scout.ncaaf.pipeline import run_ncaaf_pipeline

    with patch("sharp_scout.ncaaf.pipeline.load_cfb_pbp", side_effect=AssertionError("no pbp")):
        run_ncaaf_pipeline(
            demo=False,
            skip_pbp=True,
            persist=False,
            update_ledger=True,
            build_pages=True,
            week_only=False,
        )

    assert (docs / "latest_ncaaf_signals.json").read_bytes() == good_blob.encode()
    art = json.loads((tmp_path / "artifacts" / "latest_ncaaf_signals.json").read_text())
    assert art.get("publishable") is False
