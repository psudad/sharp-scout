"""ESPN + Odds API slate rows merge to one projection per ET matchup."""

from __future__ import annotations

from sharp_scout.nba.score_model.paper import dedupe_slate_projection_rows, merge_slate_projection_rows


def test_dedupe_prefers_odds_api_tip_and_lines():
    espn = {
        "event_id": "401809999",
        "away": "BOS",
        "home": "BKN",
        "kickoff": "2026-10-28T23:30:00+00:00",
        "margin": 1.0,
        "total": 220.0,
        "lines": {},
    }
    odds = {
        "event_id": "a1b2c3d4-espn-odds",
        "away": "BOS",
        "home": "BKN",
        "kickoff": "2026-10-28T23:40:00+00:00",
        "margin": 2.0,
        "total": 221.0,
        "lines": {"consensus_spread_home": 5.5, "consensus_total": 225.5},
    }
    merged = dedupe_slate_projection_rows([espn, odds])
    assert len(merged) == 1
    row = merged[0]
    assert row["kickoff"] == odds["kickoff"]
    assert row["lines"]["consensus_spread_home"] == 5.5
    assert row["margin"] == 2.0


def test_merge_keeps_lines_from_odds_when_espn_has_injury_only():
    espn = {
        "event_id": "401809999",
        "away": "DET",
        "home": "NYK",
        "kickoff": "2026-10-28T00:00:00+00:00",
        "injury_margin": 3.0,
        "lines": {},
    }
    odds = {
        "event_id": "uuid-odds",
        "away": "DET",
        "home": "NYK",
        "kickoff": "2026-10-28T00:10:00+00:00",
        "margin": 4.0,
        "lines": {"consensus_spread_home": -4.0, "consensus_total": 230.0},
    }
    out = merge_slate_projection_rows(espn, odds)
    assert out["kickoff"] == odds["kickoff"]
    assert out["lines"]["consensus_total"] == 230.0
