"""Tests for pregame run plan builder."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sharp_scout.scheduler.plan import (
    build_run_plan,
    should_run_now,
    _parse_kickoff,
)


ET = ZoneInfo("America/New_York")


def test_parse_kickoff_eastern():
    kickoff = _parse_kickoff("2025-09-07", "13:00")
    local = kickoff.astimezone(ET)
    assert local.hour == 13
    assert local.day == 7


def test_build_run_plan_counts_windows():
    kickoff = datetime(2025, 9, 7, 17, 0, tzinfo=timezone.utc)
    now = kickoff - timedelta(hours=13)
    fake_games = [
        {
            "game_id": "2025_01_TB_ATL",
            "season": 2025,
            "week": "1",
            "game_type": "REG",
            "kickoff": kickoff,
            "home_team": "ATL",
            "away_team": "TB",
            "matchup": "TB@ATL",
        }
    ]

    from sharp_scout.scheduler import plan as plan_mod

    plan_mod.upcoming_games_from_schedule = lambda **kwargs: fake_games  # type: ignore[assignment]
    plan_mod.merge_odds_kickoffs = lambda games: games  # type: ignore[assignment]

    plan = build_run_plan(now=now, horizon_days=14, windows_hours=[12, 3, 1])
    assert plan["n_runs"] == 3
    assert {r["window_hours"] for r in plan["runs"]} == {12, 3, 1}


def test_should_run_now_within_tolerance():
    kickoff = datetime(2025, 9, 7, 17, 0, tzinfo=timezone.utc)
    run_at = kickoff - timedelta(hours=3)
    plan = {
        "tolerance_minutes": 25,
        "runs": [{"run_at": run_at.isoformat(), "window_hours": 3, "matchup": "TB@ATL"}],
    }
    ok, matched = should_run_now(plan, now=run_at + timedelta(minutes=10))
    assert ok is True
    assert len(matched) == 1

    ok2, _ = should_run_now(plan, now=run_at + timedelta(hours=2))
    assert ok2 is False
