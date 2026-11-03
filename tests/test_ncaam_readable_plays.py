"""NCAAM plays must read like the other sport pages: team + line + price, book and stake."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sharp_scout.site.ncaam_page import (
    _ledger_rows,
    _render_locks,
    ncaam_book_label,
    ncaam_play_label,
)

ROOT = Path(__file__).resolve().parents[1]

ML_AWAY = {
    "market": "h2h", "side": "away", "line": None, "price": 170.0, "book": "betrivers",
    "home_team": "Columbia", "away_team": "Elon", "tip": "2026-11-03T00:00:00+00:00",
    "units": 1.0, "status": "win", "pnl_units": 1.7,
}
SPREAD_HOME = {
    "market": "spreads", "side": "home", "line": 1.0, "price": -110.0, "book": "williamhill_us",
    "home_team": "Iona", "away_team": "Vermont", "tip": "2026-11-03T00:00:00+00:00",
    "units": 1.0, "status": "pending", "ev": 0.094, "locked_at": "2026-11-02T22:38:39+00:00",
}
SPREAD_AWAY_VOID = {
    "market": "spreads", "side": "away", "selection": "Gonzaga", "line": 5.5, "price": -115.0,
    "book": "draftkings", "home_team": "Purdue", "away_team": "Gonzaga",
    "tip": "2026-11-03T00:00:00+00:00", "units": 0.0, "status": "void", "pnl_units": 0.0,
}


def test_play_labels() -> None:
    assert ncaam_play_label(ML_AWAY) == "Elon ML +170"
    assert ncaam_play_label(SPREAD_HOME) == "Iona +1 (-110)"
    assert ncaam_play_label(SPREAD_AWAY_VOID) == "Gonzaga +5.5 (-115)"
    assert ncaam_play_label({**SPREAD_HOME, "line": -3.5}) == "Iona -3.5 (-110)"
    assert ncaam_book_label("williamhill_us") == "Caesars"
    assert ncaam_book_label("espnbet") == "ESPN BET"


def test_ledger_renders_readable_plays() -> None:
    html = _ledger_rows({"plays": [ML_AWAY, SPREAD_HOME, SPREAD_AWAY_VOID, {"status": "no_play"}]})
    assert "<b>Elon ML +170</b>" in html
    assert "<b>Iona +1 (-110)</b>" in html
    assert "BetRivers" in html and "Caesars" in html
    assert "Win (+1.70u)" in html
    assert "Void (0.00u)" in html
    assert "<th>Book</th><th>Stake</th>" in html
    for raw in ("h2h", "spreads home", "h2h away", "williamhill_us", "betrivers"):
        assert raw not in html


def test_locks_render_readable_plays() -> None:
    html = _render_locks({"locks": [SPREAD_HOME]})
    assert "<b>Iona +1 (-110)</b>" in html
    assert "Caesars" in html and "1u" in html and "Spread" in html
    assert "spreads" not in html and "williamhill_us" not in html


def test_lab_pick_text_readable() -> None:
    spec = importlib.util.spec_from_file_location("build_ncaam_lab", ROOT / "scripts" / "build_ncaam_lab.py")
    lab = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(lab)
    assert lab.pick_text(ML_AWAY) == "Elon ML +170"
    assert lab.pick_text(SPREAD_AWAY_VOID) == "Gonzaga +5.5 (-115)"
    assert lab.book_label("draftkings") == "DraftKings"
