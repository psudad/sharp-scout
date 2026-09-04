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


def test_landing_has_top_nav_to_every_board_tab(site: Path):
    html = (site / "index.html").read_text()
    for name in TAB_NAMES:
        assert f'href="board.html#tab-{name}"' in html, name


def test_landing_nav_is_above_the_hero(site: Path):
    """Nav must be at the top so users can jump straight into the board."""
    body = (site / "index.html").read_text().split("<body>", 1)[1]
    assert body.index('class="tabs"') < body.index('class="lp-hero"')


def test_board_tabs_are_anchors_with_hash_targets(site: Path):
    html = (site / "board.html").read_text()
    for name in TAB_NAMES:
        assert f'href="#tab-{name}"' in html, name
        assert f'data-tab="{name}"' in html, name


def test_nfl_and_cfb_tabs_are_symmetric(site: Path):
    """NFL and CFB must mirror each other: plays, stage winners, sharp money/line
    movement, stage records, ledger, leans, and collapsible ratings + archive."""
    html = (site / "board.html").read_text()
    nfl = html[html.index('id="tab-plays"'):html.index('id="tab-cfb"')]
    cfb = html[html.index('id="tab-cfb"'):html.index('id="tab-guide"')]
    shared = (
        "Closing Line Value",
        "PLAY THESE QUANTS NOW",
        "This Week — Pregame Stage Winners",
        "Sharp Money &amp; Line Movement",
        "Stage Records (season)",
        "Ledger ·",
        "Quant Pick Leans",
        "<summary>Power Ratings</summary>",
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
    """Deep links only work if the board reads location.hash at load time."""
    html = (site / "board.html").read_text()
    assert "hashchange" in html
    assert "nameFromHash" in html
    assert "showTab(name, null)" in html


def test_board_tab_click_syncs_hash(site: Path):
    html = (site / "board.html").read_text()
    assert "replaceState(null, '', '#tab-'" in html


def test_plays_table_cells_carry_labels_for_phone_stacking(site: Path):
    html = (site / "index.html").read_text()
    for label in ("Kickoff", "Game", "Play", "Units", "EV", "Book", "Why"):
        assert f"data-label='{label}'" in html, label


def test_phone_media_query_stacks_plays_table(site: Path):
    html = (site / "index.html").read_text()
    assert "@media (max-width: 640px)" in html
    assert "content: attr(data-label)" in html
    assert ".plays-table thead { display: none; }" in html


def test_tab_strip_scrolls_on_narrow_screens(site: Path):
    html = (site / "index.html").read_text()
    assert "-webkit-overflow-scrolling: touch" in html
    assert "@media (max-width: 700px)" in html


def test_sticky_tabs_not_broken_by_overflow_hidden(site: Path):
    """overflow-x:hidden on html/body would disable position:sticky."""
    html = (site / "board.html").read_text()
    assert "html, body { overflow-x: hidden; }" not in html
