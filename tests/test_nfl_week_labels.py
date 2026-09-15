"""NFL season week labels (nflverse) vs Wed–Tue betting windows."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.utils.slate import (
    nfl_display_season_week,
    nfl_display_week_bounds,
    nfl_season_week_for_matchup,
    nfl_section_heading,
)


def test_det_buf_opener_is_nfl_week_2_2026():
    kick = datetime(2026, 9, 17, 20, 15, tzinfo=timezone.utc)
    season, week = nfl_season_week_for_matchup("DET", "BUF", kick)
    assert season == 2026
    assert week == 2


def test_display_slate_week_2_after_week_1_mnf():
    """Tue after MNF: board should roll to Week 2 opener (Sep 17), not stay on Week 1."""
    now = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)
    events = [
        {
            "away_team": "DET",
            "home_team": "BUF",
            "commence_time": "2026-09-17T20:15:00+00:00",
        },
        {
            "away_team": "DEN",
            "home_team": "KC",
            "commence_time": "2026-09-14T20:15:00+00:00",
        },
    ]
    start, _end = nfl_display_week_bounds(now, events=events)
    # Rolled forward to the Week 2 betting window (Wed–Tue ET containing Sep 17 opener).
    assert start < datetime(2026, 9, 17, 20, 15, tzinfo=timezone.utc)
    season, week = nfl_display_season_week(events, now=now)
    assert season == 2026
    assert week == 2
    assert nfl_section_heading(events, now=now) == "NFL Week 2"
