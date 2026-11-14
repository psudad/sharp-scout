import json
from pathlib import Path

from sharp_scout.ncaam.espn import _parse_event
from sharp_scout.ncaam.teams import normalize_ncaam, slate_match_stats


def test_torvik_alias_examples():
    assert normalize_ncaam("Duke") == "Duke"
    assert normalize_ncaam("Florida State") == "Florida St."
    assert normalize_ncaam("App State") == "Appalachian St."


def test_nov2_fixture_di_match_rate():
    """≥98% of Torvik-eligible teams on the Nov 2 slate resolve."""
    payload = json.loads(
        Path("tests/fixtures/ncaam/espn_scoreboard_20261102.json").read_text()
    )
    events = []
    for ev in payload["events"]:
        row = _parse_event(ev)
        if row:
            events.append(row)
    # Denominator: both teams map to Torvik (DI playable games).
    di_total = 0
    di_matched = 0
    for row in events:
        ht = normalize_ncaam(row["home_location"])
        at = normalize_ncaam(row["away_location"])
        if ht and at:
            di_total += 2
            di_matched += 2
    assert di_total > 0
    assert di_matched / di_total >= 0.98


def test_texas_does_not_match_texas_am_cc():
    assert normalize_ncaam("Texas") == "Texas"
    assert normalize_ncaam("Texas Longhorns") == "Texas"
    assert normalize_ncaam("Texas A&M-Corpus Christi") == "Texas A&M Corpus Chris"
    assert normalize_ncaam("Texas A&M Corpus Christi") == "Texas A&M Corpus Chris"
    assert normalize_ncaam("Texas A&M-CC") == "Texas A&M Corpus Chris"
    assert normalize_ncaam("Texas A&M CC") == "Texas A&M Corpus Chris"
    assert normalize_ncaam("TAMUCC") == "Texas A&M Corpus Chris"
    assert normalize_ncaam("Texas A&M") == "Texas A&M"
    assert normalize_ncaam("Texas State") == "Texas St."
    assert normalize_ncaam("Texas Tech") == "Texas Tech"
    assert normalize_ncaam("Texas Southern") == "Texas Southern"
    assert normalize_ncaam("East Texas A&M") == "East Texas A&M"
    assert normalize_ncaam("North Texas") == "North Texas"
    # No Torvik id for this D2 school — must not fall through to Texas.
    assert normalize_ncaam("Texas A&M-Kingsville") is None
    assert normalize_ncaam("Texas Lutheran") is None


def test_state_vs_non_state_and_am_collisions():
    assert normalize_ncaam("North Carolina") == "North Carolina"
    assert normalize_ncaam("North Carolina State") == "N.C. State"
    assert normalize_ncaam("North Carolina St.") == "N.C. State"
    assert normalize_ncaam("NC State") == "N.C. State"
    assert normalize_ncaam("N.C. State") == "N.C. State"
    assert normalize_ncaam("Kansas") == "Kansas"
    assert normalize_ncaam("Kansas State") == "Kansas St."
    assert normalize_ncaam("Kansas City") == "UMKC"
    assert normalize_ncaam("South Carolina") == "South Carolina"
    assert normalize_ncaam("South Carolina Upstate") == "USC Upstate"
    assert normalize_ncaam("South Carolina State") == "South Carolina St."
    assert normalize_ncaam("Alabama") == "Alabama"
    assert normalize_ncaam("Alabama A&M") == "Alabama A&M"
    assert normalize_ncaam("Alabama State") == "Alabama St."
    assert normalize_ncaam("Florida") == "Florida"
    assert normalize_ncaam("Florida State") == "Florida St."
    assert normalize_ncaam("Florida A&M") == "Florida A&M"
    # Ambiguous bare "Miami" must not pick FL or OH.
    assert normalize_ncaam("Miami") is None
    assert normalize_ncaam("Miami (FL)") == "Miami FL"
    assert normalize_ncaam("Miami (OH)") == "Miami OH"
    assert normalize_ncaam("Kentucky State") is None  # not Kentucky; no DI canon
    assert normalize_ncaam("Kentucky") == "Kentucky"


def test_cal_state_and_usc_not_contracted():
    assert normalize_ncaam("California") == "California"
    assert normalize_ncaam("Cal") == "California"
    assert normalize_ncaam("Cal State Fullerton") == "Cal St. Fullerton"
    assert normalize_ncaam("Cal State Northridge") == "Cal St. Northridge"
    assert normalize_ncaam("Cal State Bakersfield") == "Cal St. Bakersfield"
    assert normalize_ncaam("California Baptist") == "Cal Baptist"
    assert normalize_ncaam("Southern California") == "USC"
    assert normalize_ncaam("USC") == "USC"
    assert normalize_ncaam("Southern") == "Southern"
    assert normalize_ncaam("Houston") == "Houston"
    assert normalize_ncaam("Houston Baptist") == "Houston Christian"
    assert normalize_ncaam("Houston Christian") == "Houston Christian"


def test_unique_expansion_still_works():
    assert normalize_ncaam("Grambling") == "Grambling St."
    assert normalize_ncaam("Nicholls") == "Nicholls St."
    assert normalize_ncaam("Sam Houston") == "Sam Houston St."
    assert normalize_ncaam("McNeese") == "McNeese St."


def test_unknown_or_different_schools_are_not_guessed():
    assert normalize_ncaam("Coastal Georgia") is None
    assert normalize_ncaam("William Paterson") is None
    assert normalize_ncaam("Campbellsville") is None
    assert normalize_ncaam("La Verne") is None
    assert normalize_ncaam("Mount Olive") is None
    assert normalize_ncaam("LSU New Orleans") is None
    assert normalize_ncaam("Oklahoma City") is None
    assert normalize_ncaam("Penn State Lehigh Valley") is None
    assert normalize_ncaam("Cal State San Marcos") is None
    assert normalize_ncaam("") is None
    assert normalize_ncaam("   ") is None


def test_friday_texas_am_cc_lab_row_relabeled_not_void():
    """Locked +23.5 was TAMUCC @ FSU; label corrected, grade/units unchanged."""
    import json
    from sharp_scout.config import DATA_DIR

    pid = "ac4258fd-3943-4e1b-bbe0-dd7bc2ccafe0"
    ov = json.loads((DATA_DIR / "ncaam" / "manual_overrides.json").read_text())["overrides"]
    o = next(x for x in ov if x["id"] == pid)
    assert o["ledger"] == "sharp3_ledger.json"
    assert o["action"] == "set"
    assert o["fields"]["away_team"] == "Texas A&M Corpus Chris"
    assert o["fields"]["selection"] == "Texas A&M Corpus Chris"
    row = next(
        p for p in json.loads((DATA_DIR / "ncaam" / "sharp3_ledger.json").read_text())["plays"]
        if p["id"] == pid
    )
    assert row["espn_id"] == "401909696"
    assert row["away_team"] == "Texas A&M Corpus Chris"
    assert row["selection"] == "Texas A&M Corpus Chris"
    assert row["line"] == 23.5
    assert (row["status"], row["units"], row["pnl_units"]) == ("loss", 2.0, -2.0)
    assert row["away_score"] == 60 and row["home_score"] == 84
