"""Shared primary navigation: lp-topnav (landing header) and auxiliary site tab bars."""

from __future__ import annotations

from typing import Literal

LpTopnavActive = Literal["plays", "results", "guide", "board", "nba"]
SiteTabsActive = Literal["plays", "results", "guide", "comments", "props", "nba", "nba_props"]
BoardTabsContext = Literal["board"]  # board uses its own NFL/CFB tablist + NBA link

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


def nba_props_nav_label() -> str:
    return f"NBA Props {NBA_TEST_BADGE}"


def render_lp_topnav(*, active: LpTopnavActive) -> str:
    """Sticky header nav on index.html (desktop + horizontal scroll on narrow screens)."""
    items: list[tuple[LpTopnavActive, str, str]] = [
        ("plays", "index.html", "Today's plays"),
        ("results", "board.html#tab-plays", "Results"),
        ("nba", "nba.html", nba_nav_label()),
        ("guide", "board.html#tab-guide", "How it works"),
        ("board", "board.html", "Full board"),
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
    """Top tab bar on props, comments, and nba.html."""
    home = '<a class="tab tab-home" href="index.html">Today&apos;s plays</a>'
    results = '<a class="tab" href="board.html#tab-plays">Results</a>'
    guide = '<a class="tab" href="board.html#tab-guide">How it works</a>'
    comments = (
        '<span class="tab tab-comments active">Comments</span>'
        if active == "comments"
        else '<a class="tab tab-aux tab-comments" href="comments.html">Comments</a>'
    )
    props = (
        '<span class="tab active">NFL Props</span>'
        if active == "props"
        else '<a class="tab tab-aux" href="props.html">NFL Props</a>'
    )
    nba = (
        f'<span class="tab tab-nba active">{nba_nav_label()}</span>'
        if active == "nba"
        else f'<a class="tab tab-aux tab-nba" href="nba.html">{nba_nav_label()}</a>'
    )
    nba_props = (
        f'<span class="tab tab-aux tab-nba-props active">{nba_props_nav_label()}</span>'
        if active == "nba_props"
        else f'<a class="tab tab-aux tab-nba-props" href="nba-props.html">{nba_props_nav_label()}</a>'
    )
    return (
        f'<div class="tabs" role="navigation" aria-label="Sections">'
        f"{home}{results}{guide}{comments}{props}{nba}{nba_props}"
        f"</div>"
    )


def render_board_nba_tab_link() -> str:
    """NBA entry appended to the main board tablist (NFL / CFB / …)."""
    return f'<a class="tab tab-aux tab-nba" href="nba.html">{nba_nav_label()}</a>'
