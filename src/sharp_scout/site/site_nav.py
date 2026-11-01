"""Shared primary navigation: lp-topnav (landing header) and auxiliary site tab bars."""

from __future__ import annotations

from typing import Literal

from sharp_scout.config import get_settings

LpTopnavActive = Literal["home", "ncaaf", "nfl", "nba", "ncaam"]
SiteTabsActive = Literal["ncaaf", "nfl", "nba", "ncaam", "comments"]
BoardTabsContext = Literal["board"]

NBA_TEST_BADGE = '<span class="nav-test-badge">test</span>'

NAV_TEST_BADGE_CSS = """
  .nav-test-badge {
    display: inline-block;
    margin-left: 3px;
    padding: 1px 4px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    vertical-align: middle;
    line-height: 1.2;
  }
  .lp-topnav a .nav-test-badge { background: rgba(255,255,255,.22); color: #fff; }
  .tab .nav-test-badge { background: rgba(30,58,95,.12); color: var(--color-navy); font-size: 8px; }
  .tab.active .nav-test-badge { background: rgba(255,255,255,.28); color: #fff; }
"""


def nba_nav_label() -> str:
    return f"NBA {NBA_TEST_BADGE}"


def site_player_props_enabled() -> bool:
    return get_settings().site_player_props_enabled


def render_lp_topnav(*, active: LpTopnavActive) -> str:
    """Sticky header nav on index.html — direct links to sport boards."""
    items: list[tuple[LpTopnavActive, str, str]] = [
        ("home", "index.html", "Home"),
        ("ncaaf", "board.html#tab-cfb", "NCAAF"),
        ("nfl", "board.html#tab-plays", "NFL"),
        ("nba", "nba.html", nba_nav_label()),
        ("ncaam", "ncaam.html", "College BB"),
    ]
    parts: list[str] = []
    for key, href, label in items:
        if active == key:
            parts.append(f'<a class="on" href="{href}">{label}</a>')
        else:
            parts.append(f'<a href="{href}">{label}</a>')
    body = "".join(parts)
    return f'<nav class="lp-topnav" aria-label="Primary">{body}</nav>'


def render_site_tabs(*, active: SiteTabsActive) -> str:
    """Top tab bar on comments, nba.html, ncaam.html, and board-adjacent pages."""
    home = '<a class="tab tab-home" href="index.html">Home</a>'

    def _tab(key: SiteTabsActive, href: str, label: str) -> str:
        if active == key:
            return f'<span class="tab active">{label}</span>'
        return f'<a class="tab" href="{href}">{label}</a>'

    ncaaf = _tab("ncaaf", "board.html#tab-cfb", "NCAAF")
    nfl = _tab("nfl", "board.html#tab-plays", "NFL")
    nba_label = nba_nav_label()
    nba = (
        f'<span class="tab tab-nba active">{nba_label}</span>'
        if active == "nba"
        else f'<a class="tab tab-aux tab-nba" href="nba.html">{nba_label}</a>'
    )
    ncaam = _tab("ncaam", "ncaam.html", "College BB")
    comments = (
        '<span class="tab tab-comments active">Comments</span>'
        if active == "comments"
        else '<a class="tab tab-aux tab-comments" href="comments.html">Comments</a>'
    )
    return (
        f'<div class="tabs" role="navigation" aria-label="Sections">'
        f"{home}{ncaaf}{nfl}{nba}{ncaam}{comments}"
        f"</div>"
    )


def render_board_aux_tab_links() -> str:
    """NBA + NCAAM entries on the football board tab strip."""
    nba = f'<a class="tab tab-aux tab-nba" href="nba.html">{nba_nav_label()}</a>'
    ncaam = '<a class="tab tab-aux tab-ncaam" href="ncaam.html">College BB</a>'
    return nba + ncaam


def render_board_nba_tab_link() -> str:
    """Backward-compatible alias for tests importing board NBA link."""
    return f'<a class="tab tab-aux tab-nba" href="nba.html">{nba_nav_label()}</a>'
