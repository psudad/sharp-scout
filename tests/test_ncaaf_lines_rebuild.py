"""Gameday full-board rebuild gating for NCAAF (T-3h / T-1h)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.scheduler.ncaaf_lines import (
    REBUILD_WINDOWS_HOURS,
    rebuild_due,
    should_run_now,
)


def _plan_with(run_at: datetime, *, window_hours, kind="prekick") -> dict:
    return {
        "tolerance_minutes": 25,
        "runs": [
            {
                "run_at": run_at.isoformat(),
                "window_hours": window_hours,
                "kind": kind,
                "matchup": "AKRON@WAKE",
                "kickoff": (run_at + timedelta(hours=window_hours or 0)).isoformat(),
            }
        ],
    }


def test_rebuild_windows_are_t3_and_t1():
    assert set(REBUILD_WINDOWS_HOURS) == {3.0, 1.0}


def test_rebuild_due_at_t3():
    run_at = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
    plan = _plan_with(run_at, window_hours=3)
    ok, hits = rebuild_due(plan, now=run_at + timedelta(minutes=10))
    assert ok is True
    assert len(hits) == 1


def test_rebuild_due_at_t1():
    run_at = datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc)
    plan = _plan_with(run_at, window_hours=1)
    ok, _ = rebuild_due(plan, now=run_at)
    assert ok is True


def test_no_rebuild_at_t6_but_snapshot_still_due():
    run_at = datetime(2026, 9, 3, 17, 0, tzinfo=timezone.utc)
    plan = _plan_with(run_at, window_hours=6)
    snap_ok, _ = should_run_now(plan, now=run_at)
    reb_ok, _ = rebuild_due(plan, now=run_at)
    assert snap_ok is True
    assert reb_ok is False


def test_open_window_never_triggers_rebuild():
    run_at = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
    plan = _plan_with(run_at, window_hours=None, kind="open")
    reb_ok, _ = rebuild_due(plan, now=run_at)
    assert reb_ok is False


def test_no_rebuild_outside_tolerance():
    run_at = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
    plan = _plan_with(run_at, window_hours=3)
    ok, _ = rebuild_due(plan, now=run_at + timedelta(hours=2))
    assert ok is False
