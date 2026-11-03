"""Public pages must not explain the model / method ("How it works")."""
from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.site.ncaam_page import render_ncaam_page_html

BANNED = (
    "How it works",
    "Monte Carlo",
    "Torvik",
    "barttorvik",
    "Model version",
    "anchor k=",
    "blended Jan",
)


def test_ncaam_page_has_no_method_text():
    html = render_ncaam_page_html(
        ledger={"plays": []},
        signals={"locks": []},
        analytics_head="",
        site_css="",
        updated="now",
    )
    for s in BANNED:
        assert s not in html, s
    assert "Informational model picks only" in html
    assert "no automated betting" in html


def test_ncaam_lab_has_no_method_text(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "build_ncaam_lab", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaam_lab.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    out = mod.build(tmp_path / "lab.html", now=datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc))
    html = out.read_text()
    for s in ("Picks lock 90", "no daily cap", "bounce-back", "edge under", "edge over", "money and ticket"):
        assert s not in html, s


def test_explain_copy_has_no_method_text():
    from sharp_scout.copy import explain

    blob = repr(vars(explain))
    assert "Monte Carlo" not in blob
    assert "EPA" not in blob
