"""NCAA football framework — aliases, sport config, demo pipeline, site tab."""

from __future__ import annotations

from pathlib import Path

from sharp_scout.data.action_network import mock_ncaaf_splits
from sharp_scout.data.odds_api import OddsClient, mock_ncaaf_odds_events
from sharp_scout.ledger.tracker import compute_record, empty_ledger, save_ledger
from sharp_scout.ncaaf.pipeline import run_ncaaf_pipeline
from sharp_scout.phase1.ratings import TeamPower, matchup_means
from sharp_scout.site.build import build_site
from sharp_scout.sports import NCAAF, NFL, get_sport
from sharp_scout.utils.odds import normalize_team
from sharp_scout.utils.teams import normalize_ncaaf


def test_ncaaf_sport_config():
    sport = get_sport("ncaaf")
    assert sport is NCAAF
    assert sport.odds_sport_key == "americanfootball_ncaaf"
    assert sport.action_league == "ncaaf"
    assert sport.ledger_name == "ncaaf_ledger.json"
    assert sport.base_hfa == 3.0
    assert get_sport("nfl") is NFL


def test_ncaaf_team_aliases():
    assert normalize_ncaaf("Alabama Crimson Tide") == "ALA"
    assert normalize_ncaaf("Georgia Bulldogs") == "UGA"
    assert normalize_ncaaf("Ohio State") == "OSU"
    assert normalize_ncaaf("Michigan Wolverines") == "MICH"
    assert normalize_team("Alabama Crimson Tide", sport="ncaaf") == "ALA"
    assert normalize_team("Kansas City Chiefs") == "KC"


def test_ncaaf_matchup_means_scale():
    ratings = {
        "ALA": TeamPower("ALA", 0.10, 0.05, 0, 0, 0, 0, 0.1, 0, 0.15),
        "UGA": TeamPower("UGA", 0.08, 0.07, 0, 0, 0, 0, 0.11, 0, 0.15),
    }
    nfl = matchup_means("UGA", "ALA", ratings, home_boost=2.2, sport="nfl")
    cfb = matchup_means("UGA", "ALA", ratings, home_boost=3.0, sport="ncaaf")
    assert cfb["mu_home"] > 20
    assert cfb["model_total"] > nfl["model_total"]  # higher scoring_base


def test_ncaaf_mock_clients():
    events = mock_ncaaf_odds_events()
    assert len(events) == 1
    ev = events[0]
    assert ev["away_team"] == "ALA" and ev["home_team"] == "UGA"
    assert ev["sport"] == "ncaaf"
    splits = mock_ncaaf_splits()
    assert splits[0]["away_team"] == "ALA"
    spread = splits[0]["markets"]["spread"]
    assert spread["away_money_pct"] - spread["away_bet_pct"] >= 0.20
    client = OddsClient(sport="ncaaf")
    assert client.sport_key == "americanfootball_ncaaf"


def test_ncaaf_demo_pipeline_and_stage_picks():
    result = run_ncaaf_pipeline(
        demo=True,
        persist=False,
        skip_pbp=True,
        update_ledger=False,
        build_pages=False,
    )
    assert result["sport"] == "ncaaf"
    assert result["demo"] is True
    assert result["n_games"] == 1
    game = result["games"][0]
    assert game["away_team"] == "ALA"
    assert game["home_team"] == "UGA"
    assert "model_spread" in game
    assert result["stage_picks"]
    card = result["stage_picks"][0]
    for stage in ("model", "sharp", "public", "money", "rlm", "hybrid"):
        assert stage in card["picks"]
    assert result["n_candidates"] >= 1


def test_compute_record_accepts_path(tmp_path: Path):
    path = tmp_path / "ncaaf_ledger.json"
    save_ledger(empty_ledger(), path=path)
    rec = compute_record(path=path)
    assert rec["n_plays"] == 0
    assert rec["record"] == "0-0"


def test_site_includes_cfb_tab(tmp_path: Path):
    out = build_site(docs_dir=tmp_path / "docs")
    html = (out / "index.html").read_text()
    assert "showTab('cfb'" in html
    assert "NCAAF" in html
    assert (out / "ncaaf_ledger.json").exists()
    assert (out / "ncaaf_record.json").exists()
