"""scripts/assert_ncaaf_docs_synced.py"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_assert_fails_when_docs_older_than_artifact(tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    doc = tmp_path / "docs"
    art.mkdir(parents=True)
    doc.mkdir(parents=True)
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "src"))
    stale = {"generated_at": "2026-10-27T19:56:00+00:00", "week": 9}
    fresh = {"generated_at": "2026-10-31T14:04:00+00:00", "week": 10}
    (art / "latest_ncaaf_signals.json").write_text(json.dumps(fresh))
    (doc / "latest_ncaaf_signals.json").write_text(json.dumps(stale))

    import sharp_scout.site.build as site_build

    monkeypatch.setattr(site_build, "ARTIFACTS_DIR", art)
    monkeypatch.setattr(site_build, "DOCS_DIR", doc)

    from scripts import assert_ncaaf_docs_synced as mod

    monkeypatch.setattr(mod, "ARTIFACTS_DIR", art)
    monkeypatch.setattr(mod, "DOCS_DIR", doc)
    with __import__("pytest").raises(SystemExit):
        mod.main()


def test_assert_skips_when_artifact_unpublishable(tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    doc = tmp_path / "docs"
    art.mkdir(parents=True)
    doc.mkdir(parents=True)
    stale = {"generated_at": "2026-10-27T19:56:00+00:00", "week": 9}
    fresh = {
        "generated_at": "2026-10-31T14:04:00+00:00",
        "week": 10,
        "publishable": False,
        "publish_block_reason": "skip_pbp",
    }
    (art / "latest_ncaaf_signals.json").write_text(json.dumps(fresh))
    (doc / "latest_ncaaf_signals.json").write_text(json.dumps(stale))

    from scripts import assert_ncaaf_docs_synced as mod

    monkeypatch.setattr(mod, "ARTIFACTS_DIR", art)
    monkeypatch.setattr(mod, "DOCS_DIR", doc)
    mod.main()


def test_assert_passes_when_docs_match_artifact(tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    doc = tmp_path / "docs"
    art.mkdir(parents=True)
    doc.mkdir(parents=True)
    ts = datetime(2026, 10, 31, 14, 4, tzinfo=timezone.utc).isoformat()
    body = {"generated_at": ts, "week": 10}
    blob = json.dumps(body)
    (art / "latest_ncaaf_signals.json").write_text(blob)
    (doc / "latest_ncaaf_signals.json").write_text(blob)

    from scripts import assert_ncaaf_docs_synced as mod

    monkeypatch.setattr(mod, "ARTIFACTS_DIR", art)
    monkeypatch.setattr(mod, "DOCS_DIR", doc)
    mod.main()
