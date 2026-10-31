"""scripts/check_ncaaf_pipeline_schedule.py"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts.check_ncaaf_pipeline_schedule as sched  # noqa: E402
import scripts.check_ncaaf_staleness as stale_mod  # noqa: E402


def test_primary_cron_always_runs(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_SCHEDULE_CRON", "7 15 * * 1-6")
    out: list[str] = []

    def capture(run: bool) -> None:
        out.append(f"run={'true' if run else 'false'}")

    monkeypatch.setattr(sched, "_set_output", capture)
    sched.main()
    assert out == ["run=true"]


def test_backup_cron_skips_when_fresh(tmp_path, monkeypatch):
    state = tmp_path / "data" / "ncaaf_rebuild_state.json"
    state.parent.mkdir(parents=True)
    now = datetime(2026, 10, 31, 15, 32, tzinfo=timezone.utc)
    state.write_text(
        json.dumps({"last_rebuild": (now - __import__("datetime").timedelta(minutes=5)).isoformat()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(stale_mod, "STATE_PATH", state)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_SCHEDULE_CRON", "32 15 * * 1-6")
    out: list[str] = []

    def capture(run: bool) -> None:
        out.append(f"run={'true' if run else 'false'}")

    monkeypatch.setattr(sched, "_set_output", capture)
    sched.main()
    assert out == ["run=false"]
