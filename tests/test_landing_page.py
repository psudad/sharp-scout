"""Landing page — board hub and navigation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sharp_scout.site.build import build_site
from sharp_scout.site.landing_page import _landing_team_display


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


def test_landing_hub_links_to_all_boards(site: Path):
    html = (site / "index.html").read_text()
    assert "Model boards" in html
    assert 'href="board.html#tab-cfb"' in html
    assert 'href="board.html#tab-plays"' in html
    assert 'href="nba.html"' in html
    assert 'href="ncaam.html"' in html
    assert "Open board" in html


def test_landing_has_my_card_via_bottom_bar(site: Path):
    html = (site / "index.html").read_text()
    assert "My card" in html
    assert "ssSlip" in html or "localStorage" in html


def test_landing_omits_board_only_sections(site: Path):
    html = (site / "index.html").read_text()
    assert "Pregame Stage Winners" not in html
    assert "NCAAF Ledger" not in html
    assert "showTab(" not in html


def test_landing_is_much_smaller_than_board(site: Path):
    landing = (site / "index.html").stat().st_size
    board = (site / "board.html").stat().st_size
    assert landing < board / 2


def test_landing_hides_early_season_banner_after_week_three(site: Path):
    html = (site / "index.html").read_text()
    assert "WEEK 1 — READ THIS FIRST" not in html


def test_landing_redirects_legacy_tab_deep_links(site: Path):
    html = (site / "index.html").read_text()
    assert "board.html' + h" in html
    assert "#tab-" in html


def test_board_links_back_to_landing(site: Path):
    html = (site / "board.html").read_text()
    assert 'href="index.html"' in html


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("North Carolina Tar Heels", "North Carolina"),
        ("Notre Dame Fighting Irish", "Notre Dame"),
        ("Oklahoma State Cowboys", "Oklahoma State"),
        ("Texas State Bobcats", "Texas State"),
        ("UCLA Bruins", "UCLA"),
        ("LSU Tigers", "LSU"),
        ("Indiana State Sycamores", "Indiana State"),
    ],
)
def test_landing_team_display_ncaaf_full_names(name: str, expected: str):
    assert _landing_team_display(name, sport="ncaaf") == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("UNC", "North Carolina"),
        ("NAVY", "Navy"),
        ("LIB", "Liberty"),
        ("ND", "Notre Dame"),
        ("UCLA", "UCLA"),
        ("LSU", "LSU"),
        ("INST", "Indiana State"),
        ("MOST", "Missouri State"),
    ],
)
def test_landing_team_display_ncaaf_bare_codes(name: str, expected: str):
    assert _landing_team_display(name, sport="ncaaf") == expected


def test_landing_team_display_ncaaf_never_title_cases_codes():
    assert _landing_team_display("unc", sport="ncaaf") == "North Carolina"
    assert _landing_team_display("ucla", sport="ncaaf") == "UCLA"
    assert _landing_team_display("lsu", sport="ncaaf") == "LSU"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("MIA", "MIA"),
        ("Miami Dolphins", "MIA"),
    ],
)
def test_landing_team_display_nfl_codes(name: str, expected: str):
    assert _landing_team_display(name, sport="nfl") == expected
