"""Yesterday ET record helpers."""

from __future__ import annotations

from datetime import date

from sharp_scout.ledger.day_record import format_yesterday_stat_value, summarize_yesterday


def test_summarize_yesterday_et_kickoff():
    day = date(2026, 11, 10)
    plays = [
        {
            "kickoff": "2026-11-11T01:00:00+00:00",
            "status": "win",
            "pnl_units": 0.91,
        },
        {
            "kickoff": "2026-11-11T03:00:00+00:00",
            "status": "loss",
            "pnl_units": -1.0,
        },
        {
            "kickoff": "2026-11-12T01:00:00+00:00",
            "status": "win",
            "pnl_units": 2.0,
        },
    ]
    s = summarize_yesterday(plays, day=day)
    assert s["record"] == "1-1"
    assert s["pnl_units"] == -0.09
    assert format_yesterday_stat_value(s) == "1-1 (-0.09u)"


def test_ncaam_page_renders_yesterday_stat(tmp_path, monkeypatch):
    monkeypatch.setenv("GA_MEASUREMENT_ID", "")
    from sharp_scout.config import get_settings
    from sharp_scout.site.ncaam_page import build_ncaam_page

    get_settings.cache_clear()
    ledger_path = tmp_path / "ncaam_ledger.json"
    ledger_path.write_text(
        '{"starting_units":100,"plays":[{"kickoff":"2026-11-11T01:00:00+00:00","status":"win","side":"away","pnl_units":1.0}]}'
    )
    try:
        build_ncaam_page(docs_dir=tmp_path, signals_path=None, ledger_path=ledger_path)
    finally:
        get_settings.cache_clear()
    html = (tmp_path / "ncaam.html").read_text()
    assert "Yesterday ·" in html
