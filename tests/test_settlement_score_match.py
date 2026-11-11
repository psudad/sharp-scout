"""Settlement team matching (aliases, accents, ambiguity)."""

from __future__ import annotations

from sharp_scout.settlement.score_match import (
    build_score_index,
    fold_accents,
    match_play_to_score,
    normalize_for_settlement,
)


def test_fold_accents_san_jose():
    assert fold_accents("San José State") == "San Jose State"


def test_normalize_aliases_ou_bsu_san_jose():
    assert normalize_for_settlement("OU", sport="ncaaf") == "OU"
    assert normalize_for_settlement("Oklahoma Sooners", sport="ncaaf") == "OU"
    assert normalize_for_settlement("BSU", sport="ncaaf") == "BSU"
    assert normalize_for_settlement("Boise State Broncos", sport="ncaaf") == "BSU"
    assert normalize_for_settlement("San José State Spartans", sport="ncaaf") == "SAN JOSE STATE"
    assert normalize_for_settlement("SJSU", sport="ncaaf") == "SAN JOSE STATE"


def test_match_by_canonical_names_and_kickoff():
    scores = [
        {
            "away_team": "OU",
            "home_team": "TEX",
            "home_score": 28,
            "away_score": 21,
            "kickoff": "2026-09-14T00:00:00+00:00",
        }
    ]
    index = build_score_index(scores, sport="ncaaf")
    play = {
        "id": "p1",
        "away_team": "Oklahoma Sooners",
        "home_team": "Texas Longhorns",
        "kickoff": "2026-09-13T23:30:00+00:00",
    }
    hit = match_play_to_score(play, index, sport="ncaaf")
    assert hit.score is not None
    assert hit.score["home_score"] == 28


def test_ambiguous_when_two_games_same_teams_in_window():
    scores = [
        {
            "away_team": "RUT",
            "home_team": "OU",
            "home_score": 10,
            "away_score": 7,
            "kickoff": "2026-09-01T00:00:00+00:00",
        },
        {
            "away_team": "RUT",
            "home_team": "OU",
            "home_score": 30,
            "away_score": 14,
            "kickoff": "2026-09-03T10:00:00+00:00",
        },
    ]
    index = build_score_index(scores, sport="ncaaf")
    play = {
        "id": "ambig",
        "away_team": "RUT",
        "home_team": "OU",
        "kickoff": "2026-09-01T01:00:00+00:00",
    }
    hit = match_play_to_score(play, index, sport="ncaaf")
    assert hit.score is not None
    assert hit.score["home_score"] == 10

    scores2 = [
        {
            "away_team": "RUT",
            "home_team": "OU",
            "home_score": 10,
            "away_score": 7,
            "kickoff": "2026-09-01T00:00:00+00:00",
        },
        {
            "away_team": "RUT",
            "home_team": "OU",
            "home_score": 30,
            "away_score": 14,
            "kickoff": "2026-09-02T10:00:00+00:00",
        },
    ]
    index2 = build_score_index(scores2, sport="ncaaf")
    play2 = {
        "id": "ambig2",
        "away_team": "RUT",
        "home_team": "OU",
        "kickoff": "2026-09-01T20:00:00+00:00",
    }
    hit2 = match_play_to_score(play2, index2, sport="ncaaf")
    assert hit2.score is None
    assert hit2.reason == "ambiguous"


def test_event_id_preferred_when_present():
    scores = [
        {
            "event_id": "espn-999",
            "away_team": "AAA",
            "home_team": "BBB",
            "home_score": 3,
            "away_score": 7,
            "kickoff": "2026-09-05T20:00:00+00:00",
        }
    ]
    index = build_score_index(scores, sport="ncaaf")
    play = {
        "event_id": "espn-999",
        "away_team": "Wrong Name",
        "home_team": "Also Wrong",
        "kickoff": "2026-09-05T20:00:00+00:00",
    }
    hit = match_play_to_score(play, index, sport="ncaaf")
    assert hit.score is not None
    assert hit.reason == "event_id"
