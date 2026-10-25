"""ESPN NBA parsing: regular season + 30-franchise filter."""

from __future__ import annotations

from sharp_scout.data.espn_nba import _is_regular_season_event, _parse_event


def _final_event(
    *,
    home: str,
    away: str,
    home_score: int = 110,
    away_score: int = 105,
    season_type: int = 2,
    name: str = "Regular Season",
) -> dict:
    return {
        "id": "999",
        "name": name,
        "season": {"type": season_type, "slug": "regular-season"},
        "competitions": [
            {
                "id": "999",
                "date": "2026-01-15T00:00:00Z",
                "status": {"type": {"name": "STATUS_FINAL"}},
                "competitors": [
                    {
                        "homeAway": "home",
                        "score": str(home_score),
                        "team": {"abbreviation": home},
                    },
                    {
                        "homeAway": "away",
                        "score": str(away_score),
                        "team": {"abbreviation": away},
                    },
                ],
            }
        ],
    }


def test_parse_event_rejects_preseason():
    ev = _final_event(home="LAL", away="GSW", season_type=1)
    assert _parse_event(ev) is None


def test_parse_event_rejects_exhibition_opponent():
    ev = _final_event(home="BOS", away="MEL")
    assert _parse_event(ev) is None


def test_parse_event_accepts_nba_regular():
    ev = _final_event(home="OKC", away="LAC")
    row = _parse_event(ev)
    assert row is not None
    assert row["home_team"] == "OKC"
    assert row["away_team"] == "LAC"


def test_is_regular_rejects_all_star_name():
    ev = _final_event(home="LAL", away="BOS", name="NBA All-Star Game")
    assert _is_regular_season_event(ev) is False
