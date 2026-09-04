"""Comments page: form fields + email delivery, present in nav everywhere."""

from __future__ import annotations

from pathlib import Path

import pytest

from sharp_scout.site.build import COMMENTS_TO_EMAIL, build_site


@pytest.fixture()
def site(tmp_path: Path, monkeypatch) -> Path:
    from sharp_scout.config import get_settings

    monkeypatch.setenv("GA_MEASUREMENT_ID", "")
    get_settings.cache_clear()
    try:
        return build_site(docs_dir=tmp_path / "docs")
    finally:
        get_settings.cache_clear()


def test_comments_page_written(site: Path):
    assert (site / "comments.html").exists()


def test_comments_page_has_all_fields(site: Path):
    html = (site / "comments.html").read_text()
    for field_id in ("cf-first", "cf-last", "cf-email", "cf-comment"):
        assert f'id="{field_id}"' in html, field_id
    assert 'type="email"' in html
    assert "<textarea" in html


def test_comments_delivers_to_jason(site: Path):
    html = (site / "comments.html").read_text()
    assert COMMENTS_TO_EMAIL == "jasoneger@gmail.com"
    assert "jasoneger@gmail.com" in html
    assert "mailto:jasoneger@gmail.com" in html


def test_comments_tab_in_every_nav(site: Path):
    for page in ("index.html", "board.html", "comments.html"):
        html = (site / page).read_text()
        assert 'href="comments.html"' in html or "tab-comments active" in html, page


def test_landing_and_board_link_to_comments(site: Path):
    assert 'href="comments.html"' in (site / "index.html").read_text()
    assert 'href="comments.html"' in (site / "board.html").read_text()


def test_comments_page_can_navigate_back(site: Path):
    html = (site / "comments.html").read_text()
    assert 'href="index.html"' in html
    assert 'href="board.html#tab-cfb"' in html


def test_comments_page_does_not_include_board_tabs_logic(site: Path):
    """It's a standalone page — no in-page tab switching that could misfire."""
    html = (site / "comments.html").read_text()
    assert "showTab(" not in html
