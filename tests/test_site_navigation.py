"""Tab navigation and phone layout for the landing page and the board."""

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


TAB_NAMES = (
    "plays",
    "cfb",
    "guide",
)


def test_landing_links_to_board_and_more_menu(site: Path):
    html = (site / "index.html").read_text()
    assert 'href="board.html"' in html
    assert 'href="comments.html"' in html
    assert 'href="props.html"' in html


def test_landing_header_is_above_hero(site: Path):
    body = (site / "index.html").read_text().split("<body", 1)[1]
    assert body.index("lp-header") < body.index("lp-hero")


def test_landing_has_mobile_bottom_bar(site: Path):
    html = (site / "index.html").read_text()
    assert "lp-bbar" in html
    assert "My card" in html


def test_board_tabs_are_anchors_with_hash_targets(site: Path):
    html = (site / "board.html").read_text()
    for name in TAB_NAMES:
        assert f'href="#tab-{name}"' in html, name
        assert f'data-tab="{name}"' in html, name


def test_nfl_and_cfb_tabs_are_symmetric(site: Path):
    html = (site / "board.html").read_text()
    nfl = html[html.index('id="tab-plays"'):html.index('id="tab-cfb"')]
    cfb = html[html.index('id="tab-cfb"'):html.index('id="tab-guide"')]
    shared = (
        "Season Overview",
        "LOCKED PLAYS — BET THESE",
        "— Pregame Stage Winners",
        "Sharp Money &amp; Line Movement",
        "Stage Records (season)",
        "Ledger ·",
        "Quant Pick Leans",
        "Prior weeks (archive)",
    )
    for token in shared:
        assert token in nfl, f"NFL missing {token}"
        assert token in cfb, f"CFB missing {token}"


def test_standalone_stages_ratings_games_tabs_are_gone(site: Path):
    html = (site / "board.html").read_text()
    for gone in ('id="tab-games"', 'id="tab-stages"', 'id="tab-ratings"',
                 'id="tab-nfl-historical"', 'id="tab-cfb-historical"'):
        assert gone not in html, gone


def test_board_routes_hash_to_tab_on_load(site: Path):
    html = (site / "board.html").read_text()
    assert "hashchange" in html
    assert "nameFromHash" in html
    assert "showTab(name, null)" in html


def test_board_tab_click_syncs_hash(site: Path):
    html = (site / "board.html").read_text()
    assert "replaceState(null, '', '#tab-'" in html


def test_aux_tabs_hidden_on_narrow_screens(site: Path):
    html = (site / "board.html").read_text()
    assert ".tab.tab-aux { display: none; }" in html


def test_sticky_tabs_not_broken_by_overflow_hidden(site: Path):
    html = (site / "board.html").read_text()
    assert "html, body { overflow-x: hidden; }" not in html
