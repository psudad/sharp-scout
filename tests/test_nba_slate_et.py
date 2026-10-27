"""ET game-date slate selection for NBA injury refresh."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sharp_scout.nba.slate_et import (
    espn_events_for_injury_window,
    format_et_slate_day_label,
    format_kickoff_day_time_et,
    group_items_by_kickoff_et_date,
    kickoff_date_et,
)

ET = ZoneInfo("America/New_York")


def test_kickoff_date_et_uses_eastern_not_utc():
    # 11 PM ET Mon Oct 27 is Tue 03:00 UTC — still Mon ET game date.
    kick = datetime(2026, 10, 28, 3, 0, tzinfo=timezone.utc)
    assert kickoff_date_et(kick) == datetime(2026, 10, 27, tzinfo=ET).date()
    # 7:10 PM ET Wed is 23:10 UTC same calendar UTC day — still Wed ET.
    wed = datetime(2026, 10, 29, 23, 10, tzinfo=timezone.utc)
    assert kickoff_date_et(wed) == datetime(2026, 10, 29, tzinfo=ET).date()


def test_format_kickoff_day_time_et_and_group_order():
    ref = datetime(2026, 10, 27, tzinfo=ET).date()
    assert format_et_slate_day_label(ref, reference=ref) == "Tonight, Tue Oct 27"
    tomorrow = ref.fromordinal(ref.toordinal() + 1)
    assert format_et_slate_day_label(tomorrow, reference=ref) == "Tomorrow, Wed Oct 28"
    late_tue = "2026-10-28T03:10:00+00:00"
    assert "Tue Oct 27" in format_kickoff_day_time_et(late_tue)
    items = [
        {"kickoff": "2026-10-29T00:00:00Z", "id": "wed"},
        {"kickoff": "2026-10-28T02:00:00Z", "id": "tue_late"},
        {"kickoff": "2026-10-28T00:00:00Z", "id": "tue"},
    ]
    groups = group_items_by_kickoff_et_date(items, reference=ref)
    assert [label for _d, label, _g in groups] == [
        "Tonight, Tue Oct 27",
        "Tomorrow, Wed Oct 28",
    ]
    assert [row["id"] for _d, _l, g in groups for row in g] == ["tue", "tue_late", "wed"]


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
