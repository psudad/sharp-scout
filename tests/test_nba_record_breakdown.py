"""NBA public record chips: by-type breakdown must match overall W-L."""

from __future__ import annotations

import json
from pathlib import Path

from sharp_scout.ledger.day_record import play_et_calendar_date, graded_status
from sharp_scout.site.nba_page import (
    _is_sharp_scout_model_line_play,
    _is_supplemental_shadow_play,
    _record_breakdown_note,
    _sharp_scout_record_summary,
)

LEDGER = Path("data/shadow/nba_ledger.json")


def _bucket_wlp(b: dict) -> tuple[int, int, int]:
    return int(b.get("w") or 0), int(b.get("l") or 0), int(b.get("p") or 0)


def test_supplemental_breakdown_wins_losses_match_overall():
    ledger = json.loads(LEDGER.read_text())
    summary = _sharp_scout_record_summary(ledger, play_filter=_is_supplemental_shadow_play)
    w = (
        _bucket_wlp(summary["spreads"])[0]
        + _bucket_wlp(summary["h2h"])[0]
        + _bucket_wlp(summary["totals"])[0]
        + _bucket_wlp(summary["props"])[0]
    )
    l = (
        _bucket_wlp(summary["spreads"])[1]
        + _bucket_wlp(summary["h2h"])[1]
        + _bucket_wlp(summary["totals"])[1]
        + _bucket_wlp(summary["props"])[1]
    )
    assert w == summary["wins"]
    assert l == summary["losses"]
    note = _record_breakdown_note(summary)
    assert "Props " in note


def test_model_breakdown_wins_losses_match_overall():
    ledger = json.loads(LEDGER.read_text())
    summary = _sharp_scout_record_summary(
        ledger, game_lines_only=True, play_filter=_is_sharp_scout_model_line_play
    )
    w = (
        _bucket_wlp(summary["spreads"])[0]
        + _bucket_wlp(summary["h2h"])[0]
        + _bucket_wlp(summary["totals"])[0]
    )
    l = (
        _bucket_wlp(summary["spreads"])[1]
        + _bucket_wlp(summary["h2h"])[1]
        + _bucket_wlp(summary["totals"])[1]
    )
    assert w == summary["wins"]
    assert l == summary["losses"]


def test_nov_15_model_graded_record_from_ledger():
    """Regression anchor: Nov 15 2026 ET Sharp Scout model game lines."""
    from datetime import date

    ledger = json.loads(LEDGER.read_text())
    day = date(2026, 11, 15)
    rows = [
        p
        for p in ledger["plays"]
        if play_et_calendar_date(p) == day
        and _is_sharp_scout_model_line_play(p)
        and graded_status(p) in ("win", "loss", "push")
    ]
    w = sum(1 for p in rows if graded_status(p) == "win")
    l = sum(1 for p in rows if graded_status(p) == "loss")
    assert (w, l) == (4, 7)
    spread_losses = [
        p
        for p in rows
        if p.get("market") == "spreads" and graded_status(p) == "loss"
    ]
    assert len(spread_losses) == 4