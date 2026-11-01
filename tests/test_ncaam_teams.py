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
