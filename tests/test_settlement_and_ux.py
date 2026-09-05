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
    assert "EV = expected value" in html
    assert "higher the EV %, the better" in html.replace("</b>", "").replace("<b>", "")


def test_board_headers_stick_on_scroll(site: Path):
    css = (site / "board.html").read_text()
    assert "position: sticky; top: 0; z-index: 4" in css
    assert "@media (min-width: 701px)" in css
