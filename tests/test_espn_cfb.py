"""ESPN CFB scoreboard tests."""

from __future__ import annotations

from sharp_scout.data.espn_cfb import _parse_event


def test_parse_event_final_score():
    event = {
        "id": "401856766",
        "week": {"number": 1},
        "season": {"year": 2026},
        "competitions": [
            {
                "id": "401856766",
                "status": {"type": {"name": "STATUS_FINAL"}},
                "competitors": [
                    {
                        "homeAway": "away",
                        "score": "15",
                        "team": {"abbreviation": "UNC", "shortDisplayName": "North Carolina"},
                    },
                    {
                        "homeAway": "home",
                        "score": "10",
                        "team": {"abbreviation": "TCU", "shortDisplayName": "TCU"},
                    },
                ],
            }
        ],
    }
    row = _parse_event(event)
    assert row is not None
    assert row["away_team"] == "UNC"
    assert row["home_team"] == "TCU"
    assert row["away_score"] == 15
    assert row["home_score"] == 10


def test_parse_event_skips_in_progress():
    event = {
        "competitions": [
            {
                "status": {"type": {"name": "STATUS_IN_PROGRESS"}},
                "competitors": [],
            }
        ]
    }
    assert _parse_event(event) is None
