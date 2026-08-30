"""College week slate + NCAAF line snapshot plan tests."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sharp_scout.scheduler.ncaaf_lines import build_line_snapshot_plan
from sharp_scout.utils.slate import college_week_bounds, filter_events_college_week, following_college_week_bounds

ET = ZoneInfo("America/New_York")


def test_college_week_bounds_friday_starts_monday():
    # Fri Aug 28 2026 10:00 ET
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    start, end = college_week_bounds(now)
    start_et = start.astimezone(ET)
    end_et = end.astimezone(ET)
    assert start_et.weekday() == 0  # Monday
    assert start_et.day == 24 and start_et.month == 8
    assert end_et.weekday() == 6  # Sunday
    assert end_et.day == 30 and end_et.month == 8


def test_following_college_week_bounds():
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    start, end = following_college_week_bounds(now)
    start_et = start.astimezone(ET)
    end_et = end.astimezone(ET)
    assert start_et.day == 31 and start_et.month == 8
    assert end_et.day == 6 and end_et.month == 9


def test_filter_events_college_week_excludes_next_week():
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    events = [
        {
            "event_id": "a",
            "home_team": "TCU",
            "away_team": "UNC",
            "commence_time": "2026-08-29T16:00:00+00:00",
        },
        {
            "event_id": "b",
            "home_team": "OSU",
            "away_team": "TEX",
            "commence_time": "2026-09-05T16:00:00+00:00",
        },
    ]
    out = filter_events_college_week(events, now=now)
    assert len(out) == 1
    assert out[0]["event_id"] == "a"


def test_filter_plays_college_week():
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    plays = [
        {"kickoff": "2026-08-29T16:00:00+00:00", "home_team": "TCU"},
        {"kickoff": "2026-09-05T16:00:00+00:00", "home_team": "OSU"},
    ]
    from sharp_scout.utils.slate import filter_plays_college_week

    out = filter_plays_college_week(plays, now=now)
    assert len(out) == 1
    assert out[0]["home_team"] == "TCU"


def test_line_plan_includes_open_and_prekick_runs():
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    events = [
        {
            "event_id": "a",
            "home_team": "TCU",
            "away_team": "UNC",
            "commence_time": "2026-08-29T20:00:00+00:00",
        },
    ]
    plan = build_line_snapshot_plan(now=now, windows_hours=(6.0, 4.0, 1.0), events=events)
    kinds = {r["kind"] for r in plan["runs"]}
    assert "open" in kinds
    assert "open_early" in kinds
    open_run = next(r for r in plan["runs"] if r["kind"] == "open")
    open_et = datetime.fromisoformat(open_run["run_at"]).astimezone(ET)
    assert open_et.weekday() == 0
    assert open_et.hour == 10
    pre = [r for r in plan["runs"] if r["kind"] == "prekick"]
    assert len(pre) == 3
    assert all(r["window_hours"] in (6.0, 4.0, 1.0) for r in pre)


def test_group_stage_cards_by_college_week():
    from sharp_scout.utils.slate import group_stage_cards_by_college_week

    cards = [
        {"event_id": "a", "kickoff": "2026-08-29T16:00:00+00:00", "away_team": "UNC"},
        {"event_id": "b", "kickoff": "2026-09-05T16:00:00+00:00", "away_team": "OSU"},
    ]
    grouped = group_stage_cards_by_college_week(cards)
    assert len(grouped) == 2
    assert grouped[0][1][0]["away_team"] == "OSU"
    assert grouped[1][1][0]["away_team"] == "UNC"


def test_partition_stage_cards_current_historical():
    from sharp_scout.utils.slate import partition_stage_cards_current_historical

    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    cards = [
        {"event_id": "a", "kickoff": "2026-08-29T16:00:00+00:00", "away_team": "UNC"},
        {"event_id": "b", "kickoff": "2026-09-05T16:00:00+00:00", "away_team": "OSU"},
    ]
    current, historical = partition_stage_cards_current_historical(cards, now=now)
    assert len(current) == 1
    assert current[0]["event_id"] == "a"
    assert len(historical) == 1
    assert historical[0][1][0]["event_id"] == "b"
