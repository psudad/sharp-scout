"""Score matching for NFL totals board grading."""

from __future__ import annotations

from sharp_scout.nfl.totals.settle import match_score_row


def test_match_prefers_event_id():
    game = {"event_id": "abc123", "away_team": "SF", "home_team": "LAR", "kickoff": "2026-09-10T00:20:00+00:00"}
    scores = [
        {
            "event_id": "abc123",
            "away_team": "SF",
            "home_team": "LAR",
            "home_score": 7,
            "away_score": 27,
        },
        {
            "event_id": "other",
            "away_team": "SF",
            "home_team": "LAR",
            "home_score": 23,
            "away_score": 26,
        },
    ]
    hit = match_score_row(game, scores)
    assert hit is not None
    assert hit["home_score"] == 7 and hit["away_score"] == 27


def test_match_by_kickoff_date_when_no_event_id():
    game = {
        "away_team": "SF",
        "home_team": "LAR",
        "kickoff": "2026-09-10T00:20:00+00:00",
        "season": 2026,
        "week": 1,
    }
    scores = [
        {
            "away_team": "SF",
            "home_team": "LAR",
            "home_score": 7,
            "away_score": 27,
            "season": 2026,
            "week": 1,
            "gameday": "2026-09-09",
        }
    ]
    hit = match_score_row(game, scores)
    assert hit is not None
    assert hit["away_score"] == 27


def test_tracker_lookup_requires_date_not_bare_pair():
    from sharp_scout.ledger.tracker import settle_from_scores
    import json
    from pathlib import Path

    ledger = {
        "plays": [],
        "stage_cards": [
            {
                "event_id": "e1",
                "away_team": "SF",
                "home_team": "LAR",
                "market": "total",
                "kickoff": "2026-09-10T00:20:00+00:00",
                "status": "pending",
                "picks": {
                    "model": {
                        "available": True,
                        "side": "under",
                        "line": 48.0,
                    }
                },
                "results": {},
            }
        ],
    }
    path = Path("/tmp/test_ledger_nfl_totals.json")
    path.write_text(json.dumps(ledger))
    scores = [
        {
            "away_team": "SF",
            "home_team": "LAR",
            "home_score": 7,
            "away_score": 27,
            "season": 2026,
            "week": 1,
            "gameday": "2026-09-10",
        }
    ]
    settle_from_scores(scores, path=path)
    data = json.loads(path.read_text())
    card = data["stage_cards"][0]
    assert card["home_score"] == 7
    assert card["away_score"] == 27
    assert card["results"]["model"] == "win"
