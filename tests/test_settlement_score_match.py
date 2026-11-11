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


def test_air_force_single_canonical_name():
    assert normalize_for_settlement("AF", sport="ncaaf") == "AIR FORCE"
    assert normalize_for_settlement("AFA", sport="ncaaf") == "AIR FORCE"
    assert normalize_for_settlement("Air Force Falcons", sport="ncaaf") == "AIR FORCE"


def test_miami_fl_vs_miami_oh_diverge():
    assert normalize_for_settlement("Miami Hurricanes", sport="ncaaf") == "MIA"
    assert normalize_for_settlement("Miami (OH)", sport="ncaaf") == "MIAMI OHIO"
    assert normalize_for_settlement("MIA", sport="ncaaf") == "MIA"
    assert normalize_for_settlement("M-OH", sport="ncaaf") == "MIAMI OHIO"


def test_usc_not_south_carolina():
    assert normalize_for_settlement("USC", sport="ncaaf") == "USC"
    assert normalize_for_settlement("South Carolina Gamecocks", sport="ncaaf") == "SCAR"
    assert normalize_for_settlement("SC", sport="ncaaf") == "SCAR"


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


def test_event_id_requires_team_or_kickoff_agreement():
    scores = [
        {
            "event_id": "401999",
            "source": "espn",
            "away_team": "AAA",
            "home_team": "BBB",
            "home_score": 3,
            "away_score": 7,
            "kickoff": "2026-09-05T20:00:00+00:00",
            "season": 2026,
            "week": 1,
        }
    ]
    index = build_score_index(scores, sport="ncaaf")
    play = {
        "event_id_source": "espn",
        "event_id": "401999",
        "away_team": "AAA",
        "home_team": "BBB",
        "kickoff": "2026-09-05T20:00:00+00:00",
        "season": 2026,
        "week": 1,
    }
    hit = match_play_to_score(play, index, sport="ncaaf")
    assert hit.score is not None
    assert hit.reason == "event_id"

    bad = {
        **play,
        "away_team": "Wrong",
        "home_team": "Teams",
        "kickoff": "2026-10-01T12:00:00+00:00",
    }
    miss = match_play_to_score(bad, index, sport="ncaaf")
    assert miss.score is None


def test_score_without_kickoff_needs_season_week_or_gameday():
    scores = [
        {
            "away_team": "OU",
            "home_team": "TEX",
            "home_score": 21,
            "away_score": 17,
            "season": 2026,
            "week": 5,
            "source": "espn",
            "gameday": "2026-10-11",
        }
    ]
    index = build_score_index(scores, sport="ncaaf")
    play = {
        "away_team": "Oklahoma",
        "home_team": "Texas",
        "kickoff": "2026-10-11T23:00:00+00:00",
        "season": 2026,
        "week": 5,
    }
    hit = match_play_to_score(play, index, sport="ncaaf")
    assert hit.score is not None

    play2 = {**play, "season": 2026, "week": 6}
    miss = match_play_to_score(play2, index, sport="ncaaf")
    assert miss.score is None


def test_kickoff_date_key_uses_eastern_timezone():
    from sharp_scout.settlement.score_match import _kickoff_date_key

    # 04:30 UTC on Sunday = Saturday 23:30 ET (EST) — slate day is Saturday.
    row = {"kickoff": "2026-11-08T04:30:00+00:00"}
    assert _kickoff_date_key(row) == "2026-11-07"

