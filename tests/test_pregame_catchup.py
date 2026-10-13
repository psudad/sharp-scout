"""Missed pregame windows fire late (once) instead of being skipped."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sharp_scout.scheduler.pregame import find_due_windows

KICK = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)
EV = [{"event_id": "e1", "home_team": "NO", "away_team": "MIN", "commence_time": KICK}]


def _hits(now, fired=None):
    return find_due_windows(
        EV, windows_hours=[12, 3, 1], tolerance_minutes=25, now=now, state={"fired": fired or {}}
    )


def test_missed_t12_fires_late_until_t3_takes_over():
    hits = _hits(KICK - timedelta(hours=10, minutes=10))  # cron drifted ~2h
    assert [h.window_hours for h in hits] == [12]
    assert _hits(KICK - timedelta(hours=10), fired={"e1|T-12h": {}}) == []


def test_t3_and_t1_windows():
    assert [h.window_hours for h in _hits(KICK - timedelta(hours=2, minutes=5))] == [3]
    assert [h.window_hours for h in _hits(KICK - timedelta(minutes=20))] == [1]
    assert _hits(KICK + timedelta(minutes=30)) == []


def _script():
    p = Path(__file__).resolve().parents[1] / "scripts" / "check_pregame_plan.py"
    spec = importlib.util.spec_from_file_location("check_pregame_plan", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ci_gate_catches_up_missed_run_before_kickoff():
    mod = _script()
    run_at = KICK - timedelta(hours=12)
    plan = {"tolerance_minutes": 25, "runs": [{"run_at": run_at.isoformat(), "kickoff": KICK.isoformat()}]}
    assert mod.should_run(plan, run_at + timedelta(hours=1, minutes=50))[0] is True
    assert mod.should_run(plan, run_at + timedelta(hours=7))[0] is False  # past lookback
    assert mod.should_run(dict(plan, catchup=False), run_at + timedelta(hours=2))[0] is False
