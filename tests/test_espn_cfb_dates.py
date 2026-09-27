"""ESPN CFB scoreboard date helpers."""

from __future__ import annotations

from sharp_scout.data.espn_cfb import kickoff_scoreboard_dates


def test_kickoff_scoreboard_dates_et_with_pad():
    plays = [
        {
            "kickoff": "2026-09-26T00:30:00+00:00",  # Thu Sep 25 late ET
            "home_team": "UAB",
            "away_team": "NAVY",
        }
    ]
    dates = kickoff_scoreboard_dates(plays, pad_days=1)
    assert "20260924" in dates
    assert "20260925" in dates
    assert "20260926" in dates
