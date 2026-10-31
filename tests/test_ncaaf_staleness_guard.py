"""NCAAF stale-guard CI helper (scripts/check_ncaaf_staleness.py)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts.check_ncaaf_staleness as stale_mod  # noqa: E402


def _patch_paths(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(stale_mod, "ROOT", root)
    monkeypatch.setattr(stale_mod, "SIGNALS_PATH", root / "docs" / "latest_ncaaf_signals.json")
    monkeypatch.setattr(stale_mod, "STATE_PATH", root / "data" / "ncaaf_rebuild_state.json")
    monkeypatch.setattr(stale_mod, "PLAN_PATH", root / "data" / "ncaaf_line_plan.json")


def _write_signals(root: Path, when: datetime) -> None:
    doc = root / "docs"
    doc.mkdir(parents=True, exist_ok=True)
    (doc / "latest_ncaaf_signals.json").write_text(
        json.dumps({"generated_at": when.isoformat()}),
        encoding="utf-8",
    )


def _write_plan_with_kickoff_today(root: Path, now: datetime) -> None:
    kick = now + timedelta(hours=4)
    plan = {
        "games": [{"kickoff": kick.isoformat(), "matchup": "A@B"}],
        "runs": [],
    }
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "ncaaf_line_plan.json").write_text(json.dumps(plan), encoding="utf-8")


def test_stale_on_gameday_requests_run(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
    _write_plan_with_kickoff_today(tmp_path, now)
    _write_signals(tmp_path, now - timedelta(hours=3))
    assert stale_mod.should_run_full_refresh(now=now) is True


def test_fresh_signals_skip(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
    _write_plan_with_kickoff_today(tmp_path, now)
    _write_signals(tmp_path, now - timedelta(minutes=30))
    assert stale_mod.should_run_full_refresh(now=now) is False
