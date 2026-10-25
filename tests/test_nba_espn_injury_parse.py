"""ESPN NBA injuries API shape (team on athlete, not block)."""

from __future__ import annotations

from sharp_scout.data.espn_nba import fetch_espn_nba_injuries


def test_fetch_espn_injuries_resolves_team_from_athlete(monkeypatch):
    payload = {
        "injuries": [
            {
                "id": "1",
                "displayName": "Atlanta Hawks",
                "injuries": [
                    {
                        "status": "Out",
                        "athlete": {
                            "displayName": "Mouhamed Gueye",
                            "team": {"abbreviation": "ATL", "displayName": "Atlanta Hawks"},
                        },
                    }
                ],
            }
        ]
    }

    monkeypatch.setattr(
        "sharp_scout.data.espn_nba._get_json",
        lambda url: payload,
    )
    rows = fetch_espn_nba_injuries()
    assert len(rows) == 1
    assert rows[0]["team"] == "ATL"
    assert rows[0]["player"] == "Mouhamed Gueye"
