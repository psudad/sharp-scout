"""NCAAF Action Network ↔ Odds API team name alignment."""

from sharp_scout.phase4.filters import _find_split_game
from sharp_scout.utils.teams import normalize_ncaaf, ncaaf_display_code


def test_an_abbr_matches_odds_api_school_name():
    pairs = [
        ("SJSU", "SAN JOSE STATE"),
        ("JVST", "JACKSONVILLE STATE"),
        ("NDSU", "NORTH DAKOTA STATE BISON"),
        ("SAC", "SACRAMENTO STATE HORNETS"),
        ("NMSU", "NEW MEXICO STATE"),
        ("HAW", "HAWAII"),
        ("EMU", "EASTERN MICHIGAN"),
    ]
    for an_abbr, odds_name in pairs:
        assert normalize_ncaaf(an_abbr) == normalize_ncaaf(odds_name)


def test_find_split_game_ncaaf_alias():
    splits = [
        {
            "home_team": normalize_ncaaf("USC"),
            "away_team": normalize_ncaaf("SJSU"),
            "markets": {"spread": {}},
        }
    ]
    hit = _find_split_game(splits, "USC", "SAN JOSE STATE", sport="ncaaf")
    assert hit is not None


def test_ncaaf_display_code_abbreviates_long_names():
    assert ncaaf_display_code("NORTH DAKOTA STATE BISON") == "NDSU"
    assert ncaaf_display_code("JACKSONVILLE STATE GAMECOCKS") == "JVST"
    assert ncaaf_display_code("SAN JOSE STATE") == "SJSU"
    assert ncaaf_display_code("NEW MEXICO STATE") == "NMSU"
    assert ncaaf_display_code("TCU") == "TCU"
