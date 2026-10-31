"""NCAAF stale-guard and pipeline backup gates."""

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
    monkeypatch.setattr(stale_mod, "STATE_PATH", root / "data" / "ncaaf_rebuild_state.json")
    monkeypatch.setattr(stale_mod, "PLAN_PATH", root / "data" / "ncaaf_line_plan.json")


def _write_last_rebuild(root: Path, when: datetime) -> None:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "ncaaf_rebuild_state.json").write_text(
        json.dumps({"last_rebuild": when.isoformat()}),
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
    _write_last_rebuild(tmp_path, now - timedelta(hours=3))
    assert stale_mod.should_run_full_refresh(now=now) is True


def test_fresh_last_rebuild_skips_even_if_signals_stale(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
    _write_plan_with_kickoff_today(tmp_path, now)
    _write_last_rebuild(tmp_path, now - timedelta(minutes=30))
    assert stale_mod.should_run_full_refresh(now=now) is False


def test_recent_last_rebuild_not_throttled_after_two_hours(tmp_path, monkeypatch):
    """After a successful run, guard stays off until STALE_AFTER (2h), not every 45m."""
    _patch_paths(monkeypatch, tmp_path)
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
    _write_plan_with_kickoff_today(tmp_path, now)
    _write_last_rebuild(tmp_path, now - timedelta(hours=1))
    assert stale_mod.should_run_full_refresh(now=now) is False


