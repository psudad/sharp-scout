"""Board team search tokens (alias-aware CFB/NFL matching)."""

from sharp_scout.utils.teams import matchup_search_blob, team_search_tokens


def test_ncaaf_alabama_aliases_in_blob():
    tokens = team_search_tokens("ALA", sport="ncaaf")
    assert "alabama" in tokens
    assert "ala" in tokens
    blob = matchup_search_blob("ALA", "UK", sport="ncaaf")
    assert "alabama" in blob
    assert "uk" in blob or "kentucky" in blob


def test_nfl_chiefs_aliases():
    tokens = team_search_tokens("KC", sport="nfl")
    assert "kc" in tokens
    blob = matchup_search_blob("KC", "BUF", sport="nfl")
    assert "kc" in blob
    assert "buf" in blob or "buffalo" in blob
