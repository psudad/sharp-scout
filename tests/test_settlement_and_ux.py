"""Guards for the auto-settlement host fix + landing EV explainer + sticky headers."""

from __future__ import annotations

from pathlib import Path

import pytest

from sharp_scout.data import espn_cfb
from sharp_scout.site.build import build_site


def test_espn_primary_host_is_the_working_web_api():
    # site.api.espn.com started returning 403 to automated requests, silently
    # breaking settlement. The working host must stay primary.
    assert "site.web.api.espn.com" in espn_cfb.ESPN_SCOREBOARD
    assert "site.api.espn.com" in espn_cfb.ESPN_SCOREBOARD_FALLBACK


def test_espn_requests_use_a_browser_user_agent():
    ua = espn_cfb._BROWSER_HEADERS.get("User-Agent", "")
    assert "Mozilla/5.0" in ua and "SharpScout" not in ua


def test_board_includes_client_side_live_score_polling(site: Path):
    html = (site / "board.html").read_text()
    assert "sports/football/nfl/scoreboard" in html
    assert "sports/football/college-football/scoreboard" in html
    assert "setInterval(refresh, 30000)" in html
    assert "js-live-score" in html
    assert 'id="gameday-scores-bar"' in html
    assert "scores refresh live every 30s" in html


@pytest.fixture
def site(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr("sharp_scout.site.build.DOCS_DIR", tmp_path)
    build_site(docs_dir=tmp_path)
    return tmp_path


def test_landing_explains_confidence_in_plain_english(site: Path):
    html = (site / "index.html").read_text()
    assert "How to read a play" in html
    for tier in ("Top pick", "Strong", "Good", "Lean"):
        assert tier in html
    assert "Chance to win" in html
    assert "Bet size" in html


def test_board_headers_stick_on_scroll(site: Path):
    css = (site / "board.html").read_text()
    # Header pins to the top of a capped-height scroll box (works at every width).
    assert "position: sticky; top: 0; z-index: 4" in css
    assert ".table-wrap { overflow: auto; max-height: 80vh;" in css


def test_landing_uses_card_layout_not_plays_table(site: Path):
    html = (site / "index.html").read_text()
    body = html.split("</style>", 1)[-1]
    assert "lp-card" in body
    assert 'class="plays-table' not in body
    assert "<table" not in body


def test_all_pages_have_ssq_favicon(site: Path):
    for page in ("index.html", "board.html", "comments.html"):
        html = (site / page).read_text()
        assert '<link rel="icon" type="image/svg+xml" href="assets/ssq-logo.svg">' in html, page
    assert (site / "assets" / "ssq-logo.svg").exists()


def test_win_pct_cell_tiers():
    from sharp_scout.site.build import _win_pct_cell

    # Hybrid: high win% + strong EV earns the premium tiers.
    ddiamond = _win_pct_cell(0.74, 0.20)
    assert "74%" in ddiamond and "conf-ddiamond" in ddiamond and "Top pick" in ddiamond
    diamond = _win_pct_cell(0.63, 0.12)
    assert "conf-diamond" in diamond and "Strong" in diamond and "Top pick" not in diamond
    # Band boundaries (with value clearing the gate)
    assert "conf-diamond" in _win_pct_cell(0.60, 0.06)
    assert "conf-ddiamond" in _win_pct_cell(0.70, 0.10)
    # Gold 55%+ (all posted plays are +EV, no strict value gate here)
    gold = _win_pct_cell(0.57, 0.03)
    assert "conf-gold" in gold and "Good" in gold
    assert "conf-gold" in _win_pct_cell(0.55, 0.03)
    # Lean catches everything under 55%, including +EV moneyline dogs under 50%
    assert "conf-silver" in _win_pct_cell(0.54, 0.30) and "Lean" in _win_pct_cell(0.54, 0.30)
    assert "conf-silver" in _win_pct_cell(0.38, 0.30)
    assert "—" in _win_pct_cell(None)


def test_win_pct_cell_value_gate_caps_cheap_but_likely_plays():
    """A likely play with weak EV is capped below the premium tiers."""
    from sharp_scout.site.build import _win_pct_cell

    # 74% to win but only 4% EV -> fails Diamond (5%) and Double Diamond (10%) gates.
    assert "conf-gold" in _win_pct_cell(0.74, 0.04)
    # 65% to win but only 3% EV -> fails Diamond gate, capped at Gold.
    assert "conf-gold" in _win_pct_cell(0.65, 0.03)
    # 72% to win with 6% EV -> clears Diamond but not Double Diamond.
    assert "conf-diamond" in _win_pct_cell(0.72, 0.06)
    # Missing EV is treated as no value -> capped at Silver even if likely.
    assert "conf-silver" in _win_pct_cell(0.75, None)


def test_plays_table_has_win_pct_alongside_ev(site: Path):
    # Board always has the ledger table with Win % header
    board = (site / "board.html").read_text()
    assert "<th>Win %</th>" in board
    
    # Landing page only has Win % header if there are plays to show
    landing = (site / "index.html").read_text()
    has_plays_table = '<table' in landing and 'plays-table' in landing
    if has_plays_table:
        assert "<th>Win %</th>" in landing, "Landing page has plays table but missing Win % header"
    
    assert "Chance to win" in landing
