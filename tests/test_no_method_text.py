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


NBA_BANNED = (
    "A play needs a gap",
    "pt unadj",
    "after injuries",
    "Injury-adj score",
    "Raw score",
    "Raw result",
    "Inj-adj units",
    "Fair %",
    "Model / sharp",
    "prior-season blend",
    "Live total (raw / inj)",
)


def test_explain_copy_has_no_thresholds():
    from sharp_scout.copy import explain

    blob = repr(vars(explain))
    for s in ("≥12%", "≥10%", "at a ≥"):
        assert s not in blob, s


def test_nba_gap_text_has_no_rule():
    from sharp_scout.site import nba_page

    s = nba_page.spread_gap_plain_english(home="BOS", margin=4.0, consensus_spread_home=-1.0)
    t = nba_page.total_gap_plain_english(total=230.0, consensus_total=225.0)
    for txt in (s, t):
        assert "A play needs" not in txt
        assert "3+ pts" not in txt


def test_nba_page_source_has_no_method_labels():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "sharp_scout" / "site" / "nba_page.py").read_text()
    for s in NBA_BANNED:
        if s == "after injuries":  # helper still exists for tests; no longer rendered
            continue
        assert s not in src, s
    assert "{proj_html}" not in src and "{abs_html}" not in src and "{flip}" not in src


def test_board_copy_has_no_method_text():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "sharp_scout" / "site" / "build.py").read_text()
    for s in ("calibrated win probability", "no-vig probability", "EV≥5%", "EV≥10%", "premium tiers also need"):
        assert s not in src, s


def test_research_notes_not_published():
    from pathlib import Path

    docs = Path(__file__).resolve().parents[1] / "docs"
    assert not list(docs.rglob("*.md")), "research notes must live outside docs/ (Pages root)"
    for name in ("football_pace_backtest_nfl.csv", "football_pace_backtest_ncaaf.csv"):
        assert not (docs / "data" / name).exists()
