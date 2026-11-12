"""Price-aware NCAAM beat-close (EV vs Pinnacle no-vig at our line)."""

from __future__ import annotations

from sharp_scout.ncaam.clv_stats import (
    ev_at_close,
    pinnacle_fair_prob_at_bet_line,
    summarize_price_aware_beat_close,
)


def _history() -> dict[str, list[dict]]:
    return {
        "ev1|spreads|home": [
            {"ts": "2026-11-01T20:00:00+00:00", "book": "pinnacle", "line": -3.0, "price": -110},
        ],
        "ev1|spreads|away": [
            {"ts": "2026-11-01T20:00:00+00:00", "book": "pinnacle", "line": 3.0, "price": -110},
        ],
        "ev2|h2h|home": [
            {"ts": "2026-11-01T21:00:00+00:00", "book": "pinnacle", "line": None, "price": -140},
        ],
        "ev2|h2h|away": [
            {"ts": "2026-11-01T21:00:00+00:00", "book": "pinnacle", "line": None, "price": 120},
        ],
        "ev3|spreads|home": [
            {"ts": "2026-11-01T22:00:00+00:00", "book": "pinnacle", "line": -7.0, "price": -105},
        ],
        "ev3|spreads|away": [
            {"ts": "2026-11-01T22:00:00+00:00", "book": "pinnacle", "line": 7.0, "price": -115},
        ],
    }


def test_spread_beat_close_positive_ev_when_number_and_price_better():
    """Dog +4.5 at +100 vs Pinnacle close of +3.5/-110 — better line and price."""
    play = {
        "event_id": "ev1",
        "market": "spreads",
        "side": "away",
        "line": 4.5,
        "price": 100,
        "tip": "2026-11-01T22:00:00+00:00",
        "close_book": "pinnacle",
    }
    hist = _history()
    ev = ev_at_close(play, history=hist)
    assert ev is not None and ev > 0
    summary = summarize_price_aware_beat_close([play], history=hist)
    assert summary["n_beat_close"] == 1
    assert summary["beat_close_record"] == "1-0"


def test_spread_push_line_no_line_only_beat_but_ev_can_be_zero():
    """Same spread number as close, worse price → clv_points 0, EV at close ≤ 0."""
    play = {
        "event_id": "ev1",
        "market": "spreads",
        "side": "away",
        "line": 3.0,
        "price": -120,
        "tip": "2026-11-01T22:00:00+00:00",
        "clv_points": 0.0,
        "close_book": "pinnacle",
    }
    hist = _history()
    ev = ev_at_close(play, history=hist)
    assert ev is not None
    assert ev <= 0
    summary = summarize_price_aware_beat_close([play], history=hist)
    assert summary["beat_close_record"] == "0-1"
    assert summary["line_only_beat_close_record"] == "0-1"


def test_moneyline_uses_two_way_no_vig_at_close():
    play = {
        "event_id": "ev2",
        "market": "h2h",
        "side": "away",
        "line": None,
        "price": 150,
        "tip": "2026-11-01T23:00:00+00:00",
        "close_book": "pinnacle",
    }
    p = pinnacle_fair_prob_at_bet_line(play, history=_history())
    assert p is not None
    ev = ev_at_close(play, history=_history())
    assert ev is not None
    summary = summarize_price_aware_beat_close([play], history=_history())
    assert summary["n_beat_close"] == 1


def test_missing_pinnacle_close_excluded_from_denominator():
    play_with = {
        "event_id": "ev3",
        "market": "spreads",
        "side": "away",
        "line": 8.0,
        "price": -110,
        "tip": "2026-11-01T23:00:00+00:00",
        "close_book": "pinnacle",
    }
    play_without = {
        "event_id": "missing",
        "market": "spreads",
        "side": "home",
        "line": -3.0,
        "price": -110,
        "tip": "2026-11-01T23:00:00+00:00",
    }
    summary = summarize_price_aware_beat_close([play_with, play_without], history=_history())
    assert summary["n_beat_close"] == 1
