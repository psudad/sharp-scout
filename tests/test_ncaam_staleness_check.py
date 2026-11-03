"""NCAAM runner staleness alarm."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_ncaam_staleness", Path(__file__).resolve().parents[1] / "scripts" / "check_ncaam_staleness.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

TIPS = [datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc), datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)]
NOW = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)  # 7 PM ET, mid-window


def test_fresh_heartbeat_ok():
    assert not mod.ncaam_stale(NOW, TIPS, NOW - timedelta(minutes=30), "pass", None)[0]


def test_runner_in_progress_ok_even_with_old_heartbeat():
    assert not mod.ncaam_stale(NOW, TIPS, NOW - timedelta(hours=5), "exited", True)[0]


def test_down_in_window_fails():
    stale, why = mod.ncaam_stale(NOW, TIPS, NOW - timedelta(hours=3), "exited", False)
    assert stale and "no NCAAM runner" in why
    assert mod.ncaam_stale(NOW, TIPS, NOW - timedelta(minutes=10), "exited", False)[0]


def test_outside_window_and_no_games_ok():
    early = TIPS[0] - timedelta(hours=3)
    assert not mod.ncaam_stale(early, TIPS, None, "", False)[0]
    assert not mod.ncaam_stale(TIPS[-1] + timedelta(minutes=5), TIPS, None, "", False)[0]
    assert not mod.ncaam_stale(NOW, [], None, "", False)[0]


def test_missing_slate_after_noon_in_season_fails():
    noon = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)  # 1 PM ET
    assert mod.ncaam_stale(noon, None, None, "", None)[0]
    assert not mod.ncaam_stale(datetime(2026, 7, 3, 18, 0, tzinfo=timezone.utc), None, None, "", None)[0]
