"""Landing page — card layout, filters, and My card."""

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


def test_landing_leads_with_best_plays_and_board_link(site: Path):
    html = (site / "index.html").read_text()
    assert "Today's best plays" in html
    assert 'href="board.html"' in html
    assert "See the full research board" in html
    assert "Official play" in html or "No official plays" in html


def test_landing_has_filters_and_my_card(site: Path):
    html = (site / "index.html").read_text()
    assert 'data-f="sport"' in html
    assert "Any confidence" in html
    assert "Strong or better" in html
    assert "Add to my card" in html
    assert "Copy my card" in html
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


def test_landing_keeps_timing_script(site: Path):
    html = (site / "index.html").read_text()
    assert "js-timing" in html or "play-timing" in html
    assert "setInterval(tick" in html


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


def test_landing_model_leans_section(site: Path):
    html = (site / "index.html").read_text()
    assert "Model leans" in html
    assert "Lean only" in html


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("UNC", "UNC"),
        ("UCLA", "UCLA"),
        ("ND", "ND"),
        ("LIB", "LIB"),
        ("North Carolina Tar Heels", "UNC"),
        ("Notre Dame Fighting Irish", "ND"),
    ],
)
def test_landing_team_display_ncaaf_codes(name: str, expected: str):
    assert _landing_team_display(name, sport="ncaaf") == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("MIA", "MIA"),
        ("Miami Dolphins", "MIA"),
    ],
)
def test_landing_team_display_nfl_codes(name: str, expected: str):
    assert _landing_team_display(name, sport="nfl") == expected


def test_landing_team_display_ncaaf_registered_short_codes():
    assert _landing_team_display("Indiana State Sycamores", sport="ncaaf") == "INST"
    assert _landing_team_display("Missouri State Bears", sport="ncaaf") == "MOST"
    assert _landing_team_display("Tennessee State Tigers", sport="ncaaf") == "TNST"
