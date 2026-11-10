"""Rendered public HTML must not leak raw ISO UTC in user-visible Updated lines."""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path

from sharp_scout.site.ncaam_page import build_ncaam_page, render_ncaam_page_html

ROOT = Path(__file__).resolve().parents[1]


def test_ncaam_header_uses_eastern_display_not_iso(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    monkeypatch.setenv("GA_MEASUREMENT_ID", "")
    from sharp_scout.config import get_settings

    get_settings.cache_clear()
    try:
        build_ncaam_page(
            docs_dir=docs,
            signals_path=None,
            ledger_path=tmp_path / "ledger.json",
        )
    finally:
        get_settings.cache_clear()
    html = (docs / "ncaam.html").read_text()
    m = re.search(r"Updated ([^<]+)", html)
    assert m, "missing Updated line"
    shown = m.group(1)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T", shown)
    assert "+00:00" not in shown
    assert re.search(r"\d{4} at \d+:\d+ (AM|PM) E(ST|DT)", shown)


def test_render_ncaam_updated_jason_example():
    html = render_ncaam_page_html(
        ledger={"plays": [], "starting_units": 100},
        signals={"generated_at": "2026-11-09T23:46:28.289216+00:00"},
        analytics_head="",
        site_css="",
        updated="Nov 9, 2026 at 6:46 PM EST",
    )
    assert "Updated Nov 9, 2026 at 6:46 PM EST" in html


def test_ncaam_lab_updated_uses_eastern_display(tmp_path):
    spec = importlib.util.spec_from_file_location("build_ncaam_lab", ROOT / "scripts" / "build_ncaam_lab.py")
    lab = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(lab)
    fixed = datetime(2026, 11, 9, 21, 42, tzinfo=timezone.utc)
    out = tmp_path / "lab.html"
    lab.build(out, now=fixed)
    html = out.read_text()
    m = re.search(r"Updated ([^.<]+)\.", html)
    assert m, "lab page missing Updated line"
    shown = m.group(1).strip()
    assert not re.search(r"\d{4}-\d{2}-\d{2}T", shown)
    assert re.search(r"\d+:\d+ (AM|PM) E(ST|DT)", shown)
