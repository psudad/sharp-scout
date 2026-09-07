"""Tests for plain-English copy and signal deduplication."""

from __future__ import annotations

from sharp_scout.copy.explain import (
    STAGE_RECORD_TIPS,
    action_network_auth_status,
    collapse_best_signals,
    describe_splits_board,
    describe_stage_pick,
    explain_action_network_gap,
    format_kickoff_et,
    format_play_rationale,
)


def test_stage_record_tips_cover_all_lenses():
    for stage in ("hybrid", "model", "sharp", "public", "money", "sharp_edge", "rlm"):
        assert stage in STAGE_RECORD_TIPS
        assert len(STAGE_RECORD_TIPS[stage]) > 20


def test_collapse_best_signals_one_per_side():
    signals = [
        {"event_id": "e1", "market": "spreads", "side": "home", "line": 1.5, "book": "dk", "edge": 0.05},
        {"event_id": "e1", "market": "spreads", "side": "home", "line": 2.5, "book": "fd", "edge": 0.08},
        {"event_id": "e1", "market": "spreads", "side": "away", "line": -2.5, "book": "dk", "edge": 0.03},
    ]
    out = collapse_best_signals(signals)
    assert len(out) == 2
    home = next(s for s in out if s["side"] == "home")
    assert home["book"] == "fd"
    assert home["line"] == 2.5
    assert home["edge"] == 0.08


def test_format_kickoff_et():
    text = format_kickoff_et("2026-08-15T17:00:00+00:00")
    assert "ET" in text
    assert "Aug" in text
    assert "Sat" in text or "Fri" in text  # depends on ET offset
    assert ":" in text

    from sharp_scout.copy.explain import format_kickoff_compact

    compact = format_kickoff_compact("2026-09-10T00:15:00Z")
    assert "Sep" in compact
    assert "Wed" in compact
    assert "8:15" in compact
    assert "ET" in compact


def test_format_play_rationale_includes_edge():
    play = {
        "market": "spreads",
        "side": "home",
        "home_team": "NYG",
        "away_team": "MIN",
        "line": 1.5,
        "book": "draftkings",
        "price": -105,
        "p_true": 0.64,
        "p_mkt": 0.52,
        "edge": 0.12,
        "flags": {"money_split": True},
        "filter_notes": ["money-ticket gap +22% on home (money=58% tickets=36%)"],
    }
    text = format_play_rationale(play)
    assert "12.0%" in text or "12%" in text
    assert "NYG" in text


def test_explain_no_action_network_row_does_not_blame_cookie(monkeypatch):
    monkeypatch.delenv("ACTION_NETWORK_TOKEN", raising=False)
    monkeypatch.delenv("ACTION_NETWORK_COOKIE", raising=False)
    from sharp_scout.config import get_settings

    get_settings.cache_clear()
    try:
        msg = explain_action_network_gap("no_row")
        assert "not on Action Network" in msg
        assert "ACTION_NETWORK_COOKIE" not in msg

        play = {
            "market": "spreads",
            "side": "away",
            "home_team": "MIA",
            "away_team": "FLORIDA A AND M RATTLERS",
            "filter_notes": ["no Action Network split row matched"],
        }
        text = format_play_rationale(play)
        assert "not on Action Network" in text
        assert "ACTION_NETWORK_COOKIE" not in text
    finally:
        get_settings.cache_clear()


def test_explain_splits_incomplete_without_auth_suggests_setup(monkeypatch):
    monkeypatch.delenv("ACTION_NETWORK_TOKEN", raising=False)
    monkeypatch.delenv("ACTION_NETWORK_COOKIE", raising=False)
    from sharp_scout.config import get_settings

    get_settings.cache_clear()
    try:
        msg = explain_action_network_gap("incomplete")
        assert "ACTION_NETWORK_TOKEN" in msg
        assert "diagnose_action_network.py" in msg
    finally:
        get_settings.cache_clear()


def test_explain_splits_incomplete_with_auth_suggests_refresh(monkeypatch):
    monkeypatch.setenv("ACTION_NETWORK_TOKEN", "Bearer test-token")
    monkeypatch.delenv("ACTION_NETWORK_COOKIE", raising=False)
    from sharp_scout.config import get_settings

    get_settings.cache_clear()
    try:
        assert action_network_auth_status()["configured"] is True
        msg = explain_action_network_gap("incomplete")
        assert "expired" in msg.lower()
        assert "ACTION_NETWORK_COOKIE" not in msg

        play = {
            "market": "spreads",
            "side": "home",
            "home_team": "BUF",
            "away_team": "KC",
            "filter_notes": ["splits incomplete (money/ticket % missing — run scripts/diagnose_action_network.py)"],
        }
        text = format_play_rationale(play)
        assert "expired" in text.lower()
        assert "ACTION_NETWORK_COOKIE" not in text
    finally:
        get_settings.cache_clear()


def test_describe_splits_board_no_row(monkeypatch):
    monkeypatch.delenv("ACTION_NETWORK_TOKEN", raising=False)
    monkeypatch.delenv("ACTION_NETWORK_COOKIE", raising=False)
    from sharp_scout.config import get_settings

    get_settings.cache_clear()
    try:
        text = describe_splits_board({"available": False, "reason": "no Action Network row matched"})
        assert "not on Action Network" in text
    finally:
        get_settings.cache_clear()


def test_describe_stage_pick_no_row(monkeypatch):
    monkeypatch.delenv("ACTION_NETWORK_TOKEN", raising=False)
    monkeypatch.delenv("ACTION_NETWORK_COOKIE", raising=False)
    from sharp_scout.config import get_settings

    get_settings.cache_clear()
    try:
        text = describe_stage_pick(
            "money",
            {"available": False, "reason": "no Action Network row"},
            "MIA",
            "FLORIDA A AND M RATTLERS",
        )
        assert "not on Action Network" in text
    finally:
        get_settings.cache_clear()
