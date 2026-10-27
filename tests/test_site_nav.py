"""Shared site navigation (NBA link in top nav / tab bars)."""

from __future__ import annotations

from sharp_scout.site.site_nav import (
    nba_nav_label,
    render_board_nba_tab_link,
    render_lp_topnav,
    render_site_tabs,
)


def test_nba_nav_label_uses_test_badge():
    assert "NBA" in nba_nav_label()
    assert "nav-test-badge" in nba_nav_label()
    assert "testing)" not in nba_nav_label()


def test_lp_topnav_includes_nba_link():
    html = render_lp_topnav(active="plays")
    assert 'href="nba.html"' in html
    assert "nav-test-badge" in html
    assert 'class="on"' in html and "Today" in html


def test_site_tabs_nba_active_on_nba_page():
    html = render_site_tabs(active="nba")
    assert 'class="tab tab-nba active"' in html
    assert 'href="nba.html"' not in html
    assert 'href="nba-props.html"' in html


def test_site_tabs_nba_props_active():
    html = render_site_tabs(active="nba_props")
    assert "tab-nba-props active" in html
    assert 'href="nba-props.html"' not in html
    assert 'href="nba.html"' in html


def test_board_tab_includes_nba():
    html = render_board_nba_tab_link()
    assert 'href="nba.html"' in html
    assert "tab-nba" in html
