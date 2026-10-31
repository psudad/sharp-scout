"""scripts/check_ncaaf_pipeline_schedule.py and slot gating."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts.check_ncaaf_pipeline_schedule as sched  # noqa: E402
import scripts.check_ncaaf_staleness as stale_mod  # noqa: E402


def _state(tmp_path: Path, when: datetime) -> Path:
    p = tmp_path / "data" / "ncaaf_rebuild_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last_rebuild": when.isoformat()}), encoding="utf-8")
    return p


def test_on_time_primary_then_both_backups_skip(tmp_path, monkeypatch):
    """Primary ~15:12 UTC finish → +25 and +50 backups skip."""
    state = _state(tmp_path, datetime(2026, 10, 31, 15, 12, tzinfo=timezone.utc))
    monkeypatch.setattr(stale_mod, "STATE_PATH", state)

    assert stale_mod.needs_pipeline_backup_refresh(
        now=datetime(2026, 10, 31, 15, 32, tzinfo=timezone.utc),
        backup_cron="32 15 * * 1-6",
    ) is False
    assert stale_mod.needs_pipeline_backup_refresh(
        now=datetime(2026, 10, 31, 15, 57, tzinfo=timezone.utc),
        backup_cron="57 15 * * 1-6",
    ) is False


def test_missed_primary_plus25_runs_plus50_skips(tmp_path, monkeypatch):
    state = _state(tmp_path, datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(stale_mod, "STATE_PATH", state)

    t25 = datetime(2026, 10, 31, 15, 32, tzinfo=timezone.utc)
    assert stale_mod.needs_pipeline_backup_refresh(now=t25, backup_cron="32 15 * * 1-6") is True

    # +25 backup completed
    state.write_text(
        json.dumps({"last_rebuild": datetime(2026, 10, 31, 15, 35, tzinfo=timezone.utc).isoformat()}),
        encoding="utf-8",
    )
    t50 = datetime(2026, 10, 31, 15, 57, tzinfo=timezone.utc)
    assert stale_mod.needs_pipeline_backup_refresh(now=t50, backup_cron="57 15 * * 1-6") is False


def test_delayed_primary_skips_after_backup_ran(tmp_path, monkeypatch):
    state = _state(tmp_path, datetime(2026, 10, 31, 15, 35, tzinfo=timezone.utc))
    monkeypatch.setattr(stale_mod, "STATE_PATH", state)

    late_primary = datetime(2026, 10, 31, 15, 45, tzinfo=timezone.utc)
    assert stale_mod.should_run_primary_slot(cron="7 15 * * 1-6", now=late_primary) is False


def test_primary_cron_runs_when_no_recent_rebuild(tmp_path, monkeypatch):
    state = _state(tmp_path, datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(stale_mod, "STATE_PATH", state)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_SCHEDULE_CRON", "7 15 * * 1-6")
    out: list[str] = []

    def capture(run: bool) -> None:
        out.append(f"run={'true' if run else 'false'}")

    monkeypatch.setattr(sched, "_set_output", capture)
    sched.main()
    assert out == ["run=true"]


def test_primary_cron_skips_when_recent_rebuild(tmp_path, monkeypatch):
    state = _state(tmp_path, datetime(2026, 10, 31, 15, 35, tzinfo=timezone.utc))
    monkeypatch.setattr(stale_mod, "STATE_PATH", state)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_SCHEDULE_CRON", "7 15 * * 1-6")
    out: list[str] = []

    def capture(run: bool) -> None:
        out.append(f"run={'true' if run else 'false'}")

    monkeypatch.setattr(sched, "_set_output", capture)
    sched.main()
    assert out == ["run=false"]


def test_backup_cron_integration_skips_after_primary(tmp_path, monkeypatch):
    state = _state(tmp_path, datetime(2026, 10, 31, 15, 12, tzinfo=timezone.utc))
    monkeypatch.setattr(stale_mod, "STATE_PATH", state)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_SCHEDULE_CRON", "32 15 * * 1-6")
    out: list[str] = []

    def capture(run: bool) -> None:
        out.append(f"run={'true' if run else 'false'}")

    monkeypatch.setattr(sched, "_set_output", capture)
    sched.main()
    assert out == ["run=false"]
