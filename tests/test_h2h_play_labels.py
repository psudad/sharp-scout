"""Moneyline (h2h) pick labels show team abbreviation + ML, not Home/Away."""

from __future__ import annotations

from sharp_scout.copy.explain import format_game_line_pick
from sharp_scout.site.build import _side_label
from sharp_scout.site.landing_page import _pick_headline_html
from sharp_scout.site.nba_page import _game_pick, _price_edge_card_title, _render_nba_play_card


def test_format_game_line_pick_h2h_home_and_away():
    home_ml = {
        "market": "h2h",
        "side": "home",
        "home_team": "IND",
        "away_team": "NYK",
    }
    away_ml = {**home_ml, "side": "away"}
    assert format_game_line_pick(home_ml) == "IND ML"
    assert format_game_line_pick(away_ml) == "NYK ML"


def test_nba_game_pick_and_card_title_h2h():
    play = {
        "market": "h2h",
        "side": "home",
        "home_team": "IND",
        "away_team": "NYK",
        "price": 230,
        "kickoff": "2026-11-14T00:10:00Z",
        "book": "fanduel",
        "edge": 0.027,
        "units": 0.29,
    }
    assert _game_pick(play) == "IND ML"
    assert _price_edge_card_title(play) == "NYK @ IND: IND ML"


def test_nba_play_card_subline_shows_ml_not_line_dash():
    play = {
        "market": "h2h",
        "side": "home",
        "home_team": "IND",
        "away_team": "NYK",
        "price": 230,
        "kickoff": "2026-11-14T00:10:00Z",
        "book": "fanduel",
        "edge": 0.027,
        "units": 0.29,
    }
    html = _render_nba_play_card(
        play,
        badge="PLAY",
        badge_cls="badge-play",
        card_cls="sharp-play",
    )
    assert "NYK @ IND · H2H · ML +230" in html
    assert "Line —" not in html


def test_totals_pick_unchanged():
    play = {"market": "totals", "side": "under", "line": 221.5, "home_team": "IND", "away_team": "NYK"}
    assert _game_pick(play) == "Under 221.5"
    assert _price_edge_card_title(play) == "NYK @ IND: Under 221.5"


def test_site_side_label_h2h():
    play = {
        "market": "h2h",
        "side": "home",
        "home_team": "BUF",
        "away_team": "MIA",
        "price": -120,
    }
    assert _side_label(play) == "BUF ML -120"


def test_landing_headline_h2h():
    play = {
        "market": "h2h",
        "side": "away",
        "home_team": "IND",
        "away_team": "NYK",
    }
    assert _pick_headline_html(play, sport="nba") == "NYK ML"
