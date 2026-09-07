"""ESPN ↔ stage-card team name convergence for ledger settlement."""

from sharp_scout.utils.odds import normalize_team


def test_espn_abbrevs_match_stage_card_long_names():
    """Stage cards use Odds API names; ESPN scores use abbreviations."""
    pairs = [
        ("UMASS MINUTEMEN", "RUT", "MASS", "RUTG"),
        ("BETHUNE COOKMAN", "UCF", "BCU", "UCF"),
        ("WEST GEORGIA", "KENNESAW STATE", "WES", "KENN"),
        ("ARKANSAS PINE BLUFF", "MIZZ", "UAPB", "MIZ"),
        ("INDIANA STATE", "PUR", "INST", "PUR"),
        ("MISSISSIPPI VALLEY STATE", "SACRAMENTO STATE", "MVSU", "SAC"),
        ("WISC", "ND", "WIS", "ND"),
        ("LAMAR", "LOUISIANA", "LAM", "UL"),
        ("MAINE", "APPALACHIAN STATE", "ME", "APP"),
    ]
    for card_away, card_home, espn_away, espn_home in pairs:
        na = normalize_team(card_away, "ncaaf")
        nh = normalize_team(card_home, "ncaaf")
        ea = normalize_team(espn_away, "ncaaf")
        eh = normalize_team(espn_home, "ncaaf")
        assert na == ea and nh == eh, (
            f"{card_away}@{card_home} -> {na}@{nh} != ESPN {espn_away}@{espn_home} -> {ea}@{eh}"
        )
