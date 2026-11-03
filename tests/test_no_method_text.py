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


BOARD_REASONING_BANNED = (
    "sharp veto",
    "Fails product gate",
    "LOCKED lanes",
    "true probability vs",
    "implied at",
    "Model margin:",
    "price the favorite as",
    "lean and sim probability come first",
    "Pinnacle / Circa / Betfair",
    "Pinnacle no-vig",
    "EV below",
    "beyond the threshold",
    "<th>Why</th>",
    "<th>Why held</th>",
    "<th>Rationale</th>",
    "rationale-toggle\" onclick",
)

UNPUBLISHED_DATA_FILES = (
    "latest_signals.json",
    "latest_ncaaf_signals.json",
    "ncaaf_plays.json",
    "ncaaf_stages.json",
    "ncaaf_ratings.json",
    "nfl_ratings.json",
    "latest_props.json",
    "nba_latest_signals.json",
    "nba_paper_report.json",
    "nba_score_model.json",
    "nba_injury_lag.json",
    "nba_pace_of_play_official.json",
    "nba_pace_of_play_official.csv",
)

MODEL_FIELDS = ("p_true", "p_fair", "p_model", "model_mean", "model_spread", "model_total", "rationale", "qa_notes", "sharp_price")


def test_model_data_files_not_in_docs():
    from pathlib import Path

    docs = Path(__file__).resolve().parents[1] / "docs"
    for name in UNPUBLISHED_DATA_FILES:
        assert not (docs / name).exists(), name


def test_built_site_hides_reasoning_and_model_data(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from sharp_scout.site import build as sb

    monkeypatch.setattr(sb, "ARTIFACTS_DIR", tmp_path / "artifacts")
    docs = tmp_path / "docs"
    plays = [
        {
            "id": "x1",
            "sport": "nfl",
            "event_id": "e1",
            "kickoff": "2026-11-08T18:00:00+00:00",
            "away_team": "BAL",
            "home_team": "MIA",
            "market": "spreads",
            "side": "BAL",
            "line": -3,
            "price": -110,
            "book": "draftkings",
            "units": 1.5,
            "tier": "play",
            "status": "pending",
            "edge": 0.05,
            "p_true": 0.55,
            "p_fair": 0.52,
            "model_spread": -4.5,
            "rationale": "We project BAL -3 at 55% true probability vs 52% implied at draftkings · sharp veto: x (<50%)",
        }
    ]
    sig = {"generated_at": "2026-11-03T20:00:00+00:00", "n_games": 1, "games": [], "plays": plays, "ratings": [{"team": "BAL", "rating": 1.0}]}
    sig_path = tmp_path / "sig.json"
    sig_path.write_text(json.dumps(sig))
    sb.build_site(docs_dir=docs, signals_path=sig_path)  # real ledgers + this fake slate
    blob = "".join(p.read_text() for p in docs.glob("*.html"))
    assert "board.html" in {p.name for p in docs.glob("*.html")}
    for s in BOARD_REASONING_BANNED:
        assert s not in blob, s
    for name in UNPUBLISHED_DATA_FILES:
        assert not (docs / name).exists(), name
    for name in ("ledger.json", "ncaaf_ledger.json", "props_ledger.json"):
        data = json.loads((docs / name).read_text())
        for p in data.get("plays") or []:
            for f in MODEL_FIELDS:
                assert f not in p, (name, f)
        assert "stage_cards" not in data
