"""Landing page — plays only, with the full board one click away."""

from __future__ import annotations

from pathlib import Path

import pytest

from sharp_scout.site.build import build_site


@pytest.fixture()
def site(tmp_path: Path, monkeypatch) -> Path:
    from sharp_scout.config import get_settings

    monkeypatch.setenv("GA_MEASUREMENT_ID", "")
    get_settings.cache_clear()
    try:
        return build_site(docs_dir=tmp_path / "docs")
    finally:
        get_settings.cache_clear()


def test_landing_and_board_are_both_written(site: Path):
    assert (site / "index.html").exists()
    assert (site / "board.html").exists()


def test_landing_shows_both_sports_and_links_to_board(site: Path):
    html = (site / "index.html").read_text()
    assert "This Week's Plays" in html
    assert "College Football" in html
    assert ">NFL<" in html or "NFL" in html
    assert 'href="board.html"' in html
    assert "See the full board" in html


def test_landing_omits_board_only_sections(site: Path):
    """The point of the landing page is that it is NOT the whole board."""
    html = (site / "index.html").read_text()
    assert "Pregame Stage Winners" not in html
    assert "Quant Pick Leans" not in html
    assert "NCAAF Ledger" not in html
    assert "Stage Records" not in html
    assert "showTab(" not in html


def test_landing_is_much_smaller_than_board(site: Path):
    landing = (site / "index.html").stat().st_size
    board = (site / "board.html").stat().st_size
    assert landing < board / 2


def test_landing_keeps_timing_and_week1_warning(site: Path):
    html = (site / "index.html").read_text()
    assert "js-timing" in html or "play-timing" in html
    assert "setInterval(tick" in html
    assert "WEEK 1" in html


def test_landing_redirects_legacy_tab_deep_links(site: Path):
    html = (site / "index.html").read_text()
    assert "board.html' + h" in html
    assert "#tab-" in html


def test_board_links_back_to_landing(site: Path):
    html = (site / "board.html").read_text()
    assert 'href="index.html"' in html
