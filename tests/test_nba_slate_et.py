"""ET game-date slate selection for NBA injury refresh."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sharp_scout.nba.slate_et import espn_events_for_injury_window, kickoff_date_et

ET = ZoneInfo("America/New_York")


def test_kickoff_date_et_uses_eastern_not_utc():
    # 11 PM ET Mon Oct 27 is Tue 03:00 UTC — still Mon ET game date.
    kick = datetime(2026, 10, 28, 3, 0, tzinfo=timezone.utc)
    assert kickoff_date_et(kick) == datetime(2026, 10, 27, tzinfo=ET).date()


def test_injury_window_includes_all_of_today_et_plus_horizon_tomorrow():
    now = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)  # 11 AM ET
    events = [
        {"event_id": "1", "home_team": "BOS", "away_team": "BKN", "kickoff": "2026-10-27T23:30:00Z"},
        {"event_id": "2", "home_team": "NYK", "away_team": "DET", "kickoff": "2026-10-28T00:00:00Z"},
        {"event_id": "3", "home_team": "LAL", "away_team": "POR", "kickoff": "2026-10-28T03:00:00Z"},
        {"event_id": "4", "home_team": "PHI", "away_team": "IND", "kickoff": "2026-10-28T23:00:00Z"},
    ]
    picked = espn_events_for_injury_window(events, now=now, horizon_hours=36.0)
    ids = {e["event_id"] for e in picked}
    assert ids == {"1", "2", "3", "4"}
