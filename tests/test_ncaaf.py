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
    assert result["n_validated"] >= 1
    assert result["stage_picks"]
    card = result["stage_picks"][0]
    for stage in ("model", "sharp", "public", "money", "rlm", "hybrid"):
        assert stage in card["picks"]
    assert result["n_candidates"] >= 1
    assert any(s["filter_passed"] for s in result["signals"])


def test_compute_record_accepts_path(tmp_path: Path):
    path = tmp_path / "ncaaf_ledger.json"
    save_ledger(empty_ledger(), path=path)
    rec = compute_record(path=path)
    assert rec["n_plays"] == 0
    assert rec["record"] == "0-0"


def test_resolve_board_updated_at_uses_latest_pipeline_timestamp():
    from sharp_scout.site.build import _resolve_board_updated_at

    ts = _resolve_board_updated_at(
        nfl_signals={"generated_at": "2026-08-31T20:00:00+00:00"},
        ncaaf_signals={"generated_at": "2026-08-31T21:17:31+00:00"},
        nfl_ledger={"updated_at": "2026-08-31T19:00:00+00:00"},
        ncaaf_ledger={"updated_at": "2026-08-31T20:45:00+00:00"},
    )
    assert "Aug 31" in ts
    assert "ET" in ts
    # 21:17 UTC = 5:17 PM ET (EDT)
    assert "5:17 PM" in ts


def test_site_includes_board_updated_bar(tmp_path: Path, monkeypatch):
    from sharp_scout.config import get_settings

    monkeypatch.setenv("GA_MEASUREMENT_ID", "")
    get_settings.cache_clear()
    try:
        out = build_site(docs_dir=tmp_path / "docs")
    finally:
        get_settings.cache_clear()
    # The full board now lives at board.html; index.html is the plays-only landing page.
    html = (out / "board.html").read_text()
    # Tabs are anchors with hash targets so they can be deep-linked.
    assert 'data-tab="cfb"' in html
    assert "NCAAF" in html or "CFB" in html
    assert "This Week — Pregame Stage Winners" in html
    assert "This Week's Plays" in html
    assert "NCAAF Ledger" in html
    assert "Quant Pick Leans" in html
    assert "lean-row-sharp-play" in html
    assert "Sharp Play" in html
    assert "Sharp Scout Quant" in html
    assert "board-updated-bar" in html
    assert "Picks &amp; prices updated" in html
    # Historical is now folded into each sport tab as a collapsible archive.
    assert "Prior weeks (archive)" in html
    assert "This Week — Pregame Stage Winners" in html
    assert "NCAAF Power Ratings" not in html
    assert "Closing Line Value" in html
    assert "Cormorant Garamond" in html
    assert "Inconsolata" in html
    assert "--color-navy" in html
    assert "googletagmanager.com" not in html
    assert "downloadTableCsv" in html
    assert "csv-btn" in html
    assert (out / "ncaaf_ledger.json").exists()
    assert (out / "ncaaf_record.json").exists()


def test_historical_week_renders_csv_export_buttons():
    from datetime import datetime, timezone

    from sharp_scout.site.build import _render_cfb_historical_weeks

    week = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
    cards = [
        {
            "event_id": "e1",
            "home_team": "TCU",
            "away_team": "UNC",
            "market": "spread",
            "kickoff": "2026-08-29T16:00:00+00:00",
            "picks": {
                "hybrid": {"available": True, "side": "home", "team": "TCU", "reason": "model lean"},
                "model": {"available": True, "side": "home", "team": "TCU"},
                "sharp": {"available": True, "side": "home", "team": "TCU"},
                "public": {"available": True, "side": "home", "team": "TCU"},
                "money": {"available": True, "side": "home", "team": "TCU"},
                "sharp_edge": {"available": False},
                "rlm": {"available": False},
            },
        }
    ]
    html = _render_cfb_historical_weeks([(week, cards)], ledger_plays=[])
    assert "Weekly Lens Scorecard" in html
    assert html.index("Weekly Lens Scorecard") < html.index("Quant Pick Leans")
    assert html.index("Quant Pick Leans") < html.index("Pregame Stage Winners")
    assert "Sharp Plays (ledger)" in html
    assert "hist-cfb-stages-2026-08-24" in html
    assert "hist-cfb-leans-2026-08-24" in html
    assert "sharp-scout-cfb-stages-2026-08-24.csv" in html
    assert "sharp-scout-cfb-leans-2026-08-24.csv" in html
    assert "Download CSV" in html


def test_extract_hybrid_leans_flags_sharp_plays(tmp_path: Path):
    from sharp_scout.site.build import _extract_hybrid_leans

    cards = [
        {
            "event_id": "e1",
            "home_team": "TCU",
            "away_team": "UNC",
            "market": "h2h",
            "picks": {
                "hybrid": {
                    "available": True,
                    "side": "away",
                    "team": "UNC",
                    "reason": "validated play EV=20% @ dk",
                }
            },
        },
        {
            "event_id": "e2",
            "home_team": "USC",
            "away_team": "SJSU",
            "market": "spread",
            "picks": {
                "hybrid": {
                    "available": True,
                    "side": "home",
                    "team": "USC",
                    "reason": "model aligned with sharp (no validated edge)",
                }
            },
        },
    ]
    ledger = [
        {"event_id": "e1", "market": "h2h", "side": "away"},
    ]
    rows = _extract_hybrid_leans(cards, ledger_plays=ledger)
    assert len(rows) == 2
    sharp = [row for row in rows if row.get("is_sharp_play")]
    leans = [row for row in rows if not row.get("is_sharp_play")]
    assert len(sharp) == 1
    assert sharp[0]["kind"] == "sharp_play"
    assert len(leans) == 1
    assert leans[0]["pick"]["team"] == "USC"
    assert leans[0]["kind"] == "aligned"


def test_render_analytics_head():
    from sharp_scout.site.build import _render_analytics_head

    assert _render_analytics_head("") == ""
    html = _render_analytics_head("G-TEST1234")
    assert "G-TEST1234" in html
    assert "googletagmanager.com" in html
    assert "anonymize_ip" in html


def test_build_site_includes_analytics_when_configured(monkeypatch, tmp_path):
    from sharp_scout.config import get_settings
    from sharp_scout.site.build import build_site

    monkeypatch.setenv("GA_MEASUREMENT_ID", "G-ABCD1234")
    get_settings.cache_clear()
    try:
        out = build_site(docs_dir=tmp_path / "docs")
        html = (out / "index.html").read_text()
        assert "G-ABCD1234" in html
        assert "googletagmanager.com" in html
    finally:
        get_settings.cache_clear()
