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


@pytest.fixture
def site(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr("sharp_scout.site.build.DOCS_DIR", tmp_path)
    build_site(docs_dir=tmp_path)
    return tmp_path


def test_landing_explains_ev_in_plain_english(site: Path):
    html = (site / "index.html").read_text()
    plain = html.replace("</b>", "").replace("<b>", "").replace("</i>", "").replace("<i>", "")
    # Concise explainer: EV, Win %, and the named confidence tiers.
    assert "How to read a play" in html
    assert "EV %" in html and "how good the price is" in plain
    # All four tiers are explained, including the Double Diamond loss caveat.
    for tier in ("Double Diamond", "Diamond", "Gold", "Silver"):
        assert tier in html
    assert "> 70%" in plain or "&gt; 70%" in html
    assert "1 in every 3–4" in plain


def test_board_headers_stick_on_scroll(site: Path):
    css = (site / "board.html").read_text()
    # Header pins to the top of a capped-height scroll box (works at every width).
    assert "position: sticky; top: 0; z-index: 4" in css
    assert ".table-wrap { overflow: auto; max-height: 80vh;" in css


def test_win_pct_cell_tiers():
    from sharp_scout.site.build import _win_pct_cell

    # Hybrid: high win% + strong EV earns the premium tiers.
    ddiamond = _win_pct_cell(0.74, 0.20)
    assert "74%" in ddiamond and "conf-ddiamond" in ddiamond and "Double Diamond" in ddiamond
    diamond = _win_pct_cell(0.63, 0.12)
    assert "conf-diamond" in diamond and ">Diamond" in diamond and "Double" not in diamond
    # Band boundaries (with value clearing the gate)
    assert "conf-diamond" in _win_pct_cell(0.60, 0.06)
    assert "conf-ddiamond" in _win_pct_cell(0.70, 0.10)
    # Gold 55%+ (all posted plays are +EV, no strict value gate here)
    gold = _win_pct_cell(0.57, 0.03)
    assert "conf-gold" in gold and "Gold" in gold
    assert "conf-gold" in _win_pct_cell(0.55, 0.03)
    # Silver catches everything under 55%, including +EV moneyline dogs under 50%
    assert "conf-silver" in _win_pct_cell(0.54, 0.30) and "Silver" in _win_pct_cell(0.54, 0.30)
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
    for page in ("index.html", "board.html"):
        html = (site / page).read_text()
        assert "<th>Win %</th>" in html, page
        # Landing EV explainer describes the new column.
    landing = (site / "index.html").read_text()
    assert "Win %" in landing and "chance this exact bet cashes" in landing
