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


def test_group_of_five_mascots_and_abbrs_converge():
    """G5 rows were silently unmatched, so Public / Sharp Money never showed for them."""
    pairs = [
        ("AKR", "AKRON ZIPS"),
        ("TEM", "TEMPLE OWLS"),
        ("TLSA", "TULSA GOLDEN HURRICANE"),
        ("ECU", "EAST CAROLINA PIRATES"),
        ("KENT", "KENT STATE GOLDEN FLASHES"),
        ("NIU", "NORTHERN ILLINOIS"),
        ("APP STATE", "APPALACHIAN STATE"),
        ("USM", "SOUTHERN MISSISSIPPI"),
        ("MIAMI (OH)", "MIAMI OHIO"),
        ("UNT", "NORTH TEXAS"),
        ("TXST", "TEXAS STATE"),
        ("IDHO", "IDAHO VANDALS"),
        ("DEL", "DELAWARE BLUE HENS"),
        ("KENN", "KENNESAW STATE OWLS"),
        ("UTSA", "UTSA ROADRUNNERS"),
        ("USF", "SOUTH FLORIDA BULLS"),
        ("ULM", "UL MONROE WARHAWKS"),
        ("NEV", "NEVADA WOLF PACK"),
    ]
    for an_abbr, odds_name in pairs:
        assert normalize_ncaaf(an_abbr) == normalize_ncaaf(odds_name), (an_abbr, odds_name)


def test_school_qualifiers_never_collapse_onto_flagship():
    """Trimming trailing words blindly attaches the wrong team's splits."""
    assert normalize_ncaaf("ARKANSAS-PINE BLUFF GOLDEN LIONS") != normalize_ncaaf("ARKANSAS")
    assert normalize_ncaaf("NORTH CAROLINA A&T AGGIES") != normalize_ncaaf("NORTH CAROLINA")
    assert normalize_ncaaf("INDIANA STATE SYCAMORES") != normalize_ncaaf("INDIANA")
    assert normalize_ncaaf("SOUTHEAST MISSOURI STATE") != normalize_ncaaf("MISSOURI")
    assert normalize_ncaaf("TEXAS STATE") != normalize_ncaaf("TEXAS")


def test_registered_mascots_strip_without_an_alias():
    """AN's short_name teaches us mascots we never hardcoded (e.g. BLAZERS)."""
    from sharp_scout.utils.teams import register_mascots

    register_mascots(["Blazers", "Minutemen"])
    assert normalize_ncaaf("UAB BLAZERS") == normalize_ncaaf("UAB")
    assert normalize_ncaaf("UMASS MINUTEMEN") == normalize_ncaaf("UMASS")


def test_cross_feed_naming_variants_converge():
    """Last 5 unmatched college games were pure naming differences between feeds."""
    pairs = [
        ("UNIVERSITY AT ALBANY", "ALBANY"),
        ("THE CITADEL", "CITADEL"),
        ("YOUNGSTOWN STATE", "YOUNGSTOWN ST"),
        ("SAM HOUSTON", "SAM HOUSTON STATE"),
        ("HOUSTON CHRISTIAN", "HOUSTON BAPTIST"),
    ]
    for an_name, odds_name in pairs:
        assert normalize_ncaaf(an_name) == normalize_ncaaf(odds_name), (an_name, odds_name)


def test_directional_and_renamed_schools_stay_distinct():
    assert normalize_ncaaf("HOUSTON BAPTIST") != normalize_ncaaf("HOUSTON")
    assert normalize_ncaaf("SAM HOUSTON STATE") != normalize_ncaaf("HOUSTON")
    assert normalize_ncaaf("WESTERN KENTUCKY") != normalize_ncaaf("KENTUCKY")
    assert normalize_ncaaf("EASTERN KENTUCKY") != normalize_ncaaf("KENTUCKY")


def test_espn_score_aliases_converge_with_ledger():
    from sharp_scout.utils.teams import normalize_ncaaf

    assert normalize_ncaaf("ALB") == normalize_ncaaf("ALBANY")
    assert normalize_ncaaf("RUTG") == normalize_ncaaf("RUT")
    assert normalize_ncaaf("MASS") == normalize_ncaaf("MASSACHUSETTS")
    assert normalize_ncaaf("BUFF") == normalize_ncaaf("BUFFALO BULLS")
    assert normalize_ncaaf("EIU") == normalize_ncaaf("EASTERN ILLINOIS")
    assert normalize_ncaaf("YOUNGSTOWN ST PENGUINS") == normalize_ncaaf("YOUNGSTOWN STATE")


def test_punctuation_is_flattened():
    assert normalize_ncaaf("ARKANSAS-PINE BLUFF") == normalize_ncaaf("ARKANSAS PINE BLUFF")
    assert normalize_ncaaf("MIAMI (OH)") == normalize_ncaaf("MIAMI OHIO")


def test_action_network_prefers_mascot_free_location():
    """`location` lines up with the Odds API; `abbr` often does not."""
    from sharp_scout.data.action_network import ActionNetworkClient

    team = {"location": "North Carolina", "abbr": "UNC", "full_name": "North Carolina Tar Heels"}
    assert ActionNetworkClient._team_name(team) == "North Carolina"


def test_fcs_mascots_strip_to_school():
    assert normalize_ncaaf("MAINE BLACK BEARS") == normalize_ncaaf("MAINE")
    assert normalize_ncaaf("ARKANSAS PINE BLUFF GOLDEN LIONS") == normalize_ncaaf(
        "ARKANSAS PINE BLUFF"
    )
    assert normalize_ncaaf("INDIANA STATE SYCAMORES") == normalize_ncaaf("INDIANA STATE")
    assert normalize_ncaaf("YOUNGSTOWN ST PENGUINS") == normalize_ncaaf("YOUNGSTOWN ST")


def test_split_boards_use_ncaaf_normalizer_not_nfl():
    """Without sport='ncaaf' the NFL normalizer truncates college names to 3 letters."""
    from sharp_scout.data.splits_board import build_slate_split_boards

    events = [{"event_id": "e1", "home_team": "WAKE FOREST", "away_team": "AKRON ZIPS"}]
    splits = [
        {
            "game_id": 1,
            "home_team": "WAKE",
            "away_team": "AKR",
            "markets": {"spread": {"current_line": -24.5, "home_bet_pct": 0.7, "home_money_pct": 0.5}},
        }
    ]
    boards = build_slate_split_boards(events, splits, sport="ncaaf")
    assert boards[0]["available"] is True


def test_ncaaf_display_code_abbreviates_long_names():
    assert ncaaf_display_code("NORTH DAKOTA STATE BISON") == "NDSU"
    assert ncaaf_display_code("JACKSONVILLE STATE GAMECOCKS") == "JVST"
    assert ncaaf_display_code("SAN JOSE STATE") == "SJSU"
    assert ncaaf_display_code("NEW MEXICO STATE") == "NMSU"
    assert ncaaf_display_code("TCU") == "TCU"
