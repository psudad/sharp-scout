"""Ledger sharp fields + QA product-gate round-trip."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sharp_scout.config import get_settings
from sharp_scout.ledger.tracker import append_signals, load_ledger
from sharp_scout.qa.gate import review_play
from sharp_scout.qa.product_gate import (
    play_for_product_gate,
    product_gate_certification_log_message,
)


def _spread_play(**kw):
    kick = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    base = {
        "filter_passed": True,
        "event_id": "ev-sea-den",
        "home_team": "DEN",
        "away_team": "SEA",
        "market": "spreads",
        "side": "home",
        "line": 3.0,
        "book": "williamhill_us",
        "price": -113,
        "tier": "play",
        "edge": 0.054,
        "p_true": 0.55,
        "p_fair": 0.5171,
        "p_mkt": 0.5171,
        "sharp_book": "pinnacle",
        "sharp_price": -110,
        "kickoff": kick,
        "commence_time": kick,
        "flags": {"money_split": True, "rlm": False},
    }
    base.update(kw)
    return base


@pytest.fixture
def narrow_lanes_on(monkeypatch):
    monkeypatch.setenv("PRODUCT_NARROW_LANES_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_append_signals_persists_sharp_book_and_price(tmp_path, narrow_lanes_on):
    path = tmp_path / "ledger.json"
    sig = _spread_play()
    append_signals([sig], path=path, only_validated=False)
    row = load_ledger(path)["plays"][0]
    assert row["sharp_book"] == "pinnacle"
    assert row["sharp_price"] == -110
    assert row["p_fair"] == 0.5171


def test_lane_play_survives_qa_gate_with_persisted_sharp_fields(tmp_path, narrow_lanes_on):
    path = tmp_path / "ledger.json"
    sig = _spread_play()
    append_signals([sig], path=path, only_validated=False)
    row = load_ledger(path)["plays"][0]
    row["id"] = "sea-den"
    signals = {
        "signals": [sig],
        "games": [
            {
                "event_id": "ev-sea-den",
                "home_team": "DEN",
                "away_team": "SEA",
                "commence_time": row["kickoff"],
            }
        ],
    }
    review = review_play(row, signals, sport="nfl")
    pg = [i for i in review.issues if i.code == "product_gate"]
    assert not pg, pg


def test_legacy_row_falls_back_to_signal_sharp_book(tmp_path, narrow_lanes_on):
    sig = _spread_play()
    legacy = {
        "id": "legacy1",
        "event_id": sig["event_id"],
        "home_team": "DEN",
        "away_team": "SEA",
        "market": "spreads",
        "side": "home",
        "line": 3.0,
        "book": "williamhill_us",
        "price": -113,
        "tier": "play",
        "edge": 0.054,
        "p_fair": 0.5171,
        "p_mkt": 0.5171,
        "kickoff": sig["kickoff"],
        "status": "pending",
    }
    assert play_for_product_gate(legacy, {"signals": [sig]})["sharp_book"] == "pinnacle"
    signals = {
        "signals": [sig],
        "games": [
            {
                "event_id": sig["event_id"],
                "home_team": "DEN",
                "away_team": "SEA",
                "commence_time": sig["kickoff"],
            }
        ],
    }
    review = review_play(legacy, signals, sport="nfl")
    pg = [i for i in review.issues if i.code == "product_gate"]
    assert not pg, pg


def test_legacy_without_signal_fallback_fails_product_gate(narrow_lanes_on):
    sig = _spread_play()
    legacy = {
        "event_id": sig["event_id"],
        "market": "spreads",
        "side": "home",
        "line": 3.0,
        "tier": "play",
        "edge": 0.054,
        "p_fair": 0.5171,
        "kickoff": sig["kickoff"],
    }
    from sharp_scout.qa.product_gate import evaluate_product_play

    r = evaluate_product_play(legacy, sport="nfl")
    assert not r.ok and "Pinnacle" in r.note()


def test_product_gate_certification_log_message():
    assert product_gate_certification_log_message(2, 5) == (
        "Product gate: 2 of 5 display-week validated plays certified for ledger"
    )
    assert product_gate_certification_log_message(0, 8).startswith("Product gate: 0 of 8")
