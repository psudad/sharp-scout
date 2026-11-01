"""Shared site navigation (sport board links in top nav / tab bars)."""

from __future__ import annotations

from sharp_scout.site.site_nav import (
    nba_nav_label,
    render_board_aux_tab_links,
    render_board_nba_tab_link,
    render_lp_topnav,
    render_site_tabs,
)


def test_nba_nav_label_uses_test_badge():
    assert "NBA" in nba_nav_label()
    assert "nav-test-badge" in nba_nav_label()
    assert "testing)" not in nba_nav_label()


def test_lp_topnav_links_to_sport_boards():
    html = render_lp_topnav(active="home")
    assert 'href="board.html#tab-cfb"' in html
    assert 'href="board.html#tab-plays"' in html
    assert 'href="nba.html"' in html
    assert 'href="ncaam.html"' in html
    assert 'class="on"' in html and "Home" in html
    assert "How it works" not in html
    assert "props.html" not in html


def test_site_tabs_nba_active_on_nba_page():
    html = render_site_tabs(active="nba")
    assert 'class="tab tab-nba active"' in html
    assert 'href="nba.html"' not in html
    assert "nba-props" not in html
    assert 'href="ncaam.html"' in html


def test_site_tabs_ncaam_active():
    html = render_site_tabs(active="ncaam")
    assert "College BB" in html
    assert 'href="ncaam.html"' not in html


def test_board_aux_tabs_include_nba_and_ncaam():
    html = render_board_aux_tab_links()
    assert 'href="nba.html"' in html
    assert 'href="ncaam.html"' in html


def test_board_tab_includes_nba():
    html = render_board_nba_tab_link()
    assert 'href="nba.html"' in html
    assert "tab-nba" in html
