"""Morning preview — ledger isolation, merge rules, runner hook, page rendering."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sharp_scout.ledger.tracker import load_ledger, save_ledger
from sharp_scout.ncaam import preview as preview_mod
from sharp_scout.ncaam import preview_store as store_mod
from sharp_scout.ncaam import runner as runner_mod
from sharp_scout.ncaam.lock import LEDGER_PATH, LockWindow, append_lock, lock_window
from sharp_scout.ncaam.preview import (
    PREVIEW_STATE_ACTIVE,
    PREVIEW_STATE_DROPPED,
    merge_preview_picks,
    refresh_preview_from_snapshot,
    run_morning_preview,
)
from sharp_scout.ncaam.preview_store import ledger_overlay_status, preview_path_for_day
from sharp_scout.ncaam.runner import fetch_odds_snapshot, run_pass
from sharp_scout.site.ncaam_page import render_ncaam_page_html


@pytest.fixture
def preview_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    ncaam_dir = data / "ncaam"
    ncaam_dir.mkdir(parents=True)
    docs = tmp_path / "docs"
    docs.mkdir()
    ledger = data / "ncaam_ledger.json"
    ledger.write_text(
        '{"updated_at":"1970-01-01T00:00:00+00:00","starting_units":100,"plays":[],"stage_cards":[],"disagreements":[]}\n'
    )
    monkeypatch.setattr(store_mod, "NCAAM_PREVIEW_DIR", ncaam_dir)
    monkeypatch.setattr(store_mod, "PREVIEW_LATEST_PATH", data / "ncaam_preview_latest.json")
    monkeypatch.setattr(preview_mod, "NCAAM_PREVIEW_DIR", ncaam_dir)
    monkeypatch.setattr(preview_mod, "PREVIEW_LATEST_PATH", data / "ncaam_preview_latest.json")
    import sharp_scout.config as config_mod

    monkeypatch.setattr(config_mod, "DATA_DIR", data)
    monkeypatch.setattr(config_mod, "ROOT", tmp_path)
    from sharp_scout.site import ncaam_page as page_mod

    monkeypatch.setattr(page_mod, "DATA_DIR", data)
    monkeypatch.setattr(page_mod, "DOCS_DIR", docs)
    monkeypatch.setattr(page_mod, "NCAAM_LEDGER_PATH", ledger)
    return tmp_path, data, ncaam_dir, docs, ledger


def test_preview_never_writes_ledger(preview_env):
    _, _, _, _, ledger = preview_env
    before_n = len(load_ledger(ledger).get("plays") or [])
    run_morning_preview(demo=True, ledger_path=ledger, build_site=False)
    after_n = len(load_ledger(ledger).get("plays") or [])
    assert before_n == after_n == 0


def test_merge_marks_dropped_and_keeps_row():
    now = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    tip = (now + timedelta(hours=4)).isoformat()
    existing = [
        {
            "espn_id": "g1",
            "event_id": "g1",
            "tip": tip,
            "preview_state": PREVIEW_STATE_ACTIVE,
            "added_at_et": "Nov 18, 9:00 AM",
            "updated_at_et": "Nov 18, 9:00 AM",
            "side": "away",
            "market": "spreads",
            "line": -2.5,
            "price": -110,
        }
    ]
    merged = merge_preview_picks(existing, [], now=now)
    assert len(merged) == 1
    assert merged[0]["preview_state"] == PREVIEW_STATE_DROPPED
    assert merged[0]["added_at_et"] == "Nov 18, 9:00 AM"


def test_merge_refreshes_active_pick_line():
    now = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    tip_dt = now + timedelta(hours=4)
    existing = [
        {
            "espn_id": "g1",
            "event_id": "g1",
            "tip": tip_dt.isoformat(),
            "preview_state": PREVIEW_STATE_ACTIVE,
            "added_at_et": "Nov 18, 9:00 AM",
            "updated_at_et": "Nov 18, 9:00 AM",
            "line": -2.5,
            "away_team": "A",
            "home_team": "H",
            "side": "away",
            "market": "spreads",
            "price": -110,
        }
    ]
    fresh = [
        {
            "espn_id": "g1",
            "event_id": "g1",
            "tip": tip_dt,
            "line": -3.5,
            "away_team": "A",
            "home_team": "H",
            "side": "away",
            "market": "spreads",
            "price": -105,
            "ev": 0.05,
        }
    ]
    merged = merge_preview_picks(existing, fresh, now=now)
    assert merged[0]["line"] == -3.5
    assert merged[0]["added_at_et"] == "Nov 18, 9:00 AM"
    assert merged[0]["updated_at_et"]


def test_refresh_preview_zero_odds_cost_no_fetch(preview_env, monkeypatch):
    _, data, _, _, ledger = preview_env
    calls: list[int] = []

    def _boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("preview must not fetch odds")

    monkeypatch.setattr(runner_mod, "fetch_odds_snapshot", _boom)
    now = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    tip = now + timedelta(hours=4)
    odds_events = [
        {
            "event_id": "o1",
            "home_team": "Home",
            "away_team": "Away",
            "commence_time": tip,
            "bookmakers": {},
        }
    ]
    slate = [
        {
            "espn_id": "e1",
            "odds_event_id": "o1",
            "home_team": "Home",
            "away_team": "Away",
            "commence_time": tip,
        }
    ]
    out = refresh_preview_from_snapshot(
        odds_events,
        slate,
        ratings={},
        now=now,
        ledger_path=ledger,
        demo=True,
        build_site=False,
    )
    assert not calls
    assert out["odds_cost"] == 0


def test_run_pass_refreshes_preview_when_snapshot(preview_env, monkeypatch):
    _, data, _, _, ledger = preview_env
    refreshes: list[int] = []
    real_refresh = preview_mod.refresh_preview_from_snapshot

    def _track(*a, **k):
        refreshes.append(1)
        return real_refresh(*a, **k)

    monkeypatch.setattr(preview_mod, "refresh_preview_from_snapshot", _track)
    run_pass(demo=True, ledger_path=ledger, commit=False)
    assert refreshes == [1]


def test_live_morning_preview_rebuild_only_no_fetch(preview_env, monkeypatch):
    _, data, _, _, ledger = preview_env
    monkeypatch.setattr(runner_mod, "fetch_odds_snapshot", MagicMock(side_effect=AssertionError("no fetch")))
    out = run_morning_preview(demo=False, ledger_path=ledger, build_site=False)
    assert out.get("rebuild_only") is True
    assert out.get("odds_cost", 0) == 0


def test_page_renders_preview_and_status(preview_env):
    tmp_path, data, ncaam_dir, docs, ledger = preview_env
    now = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    run_morning_preview(demo=True, now=now, ledger_path=ledger, build_site=False)
    preview = json.loads((data / "ncaam_preview_latest.json").read_text())
    picks = preview.get("picks") or []
    if not picks:
        pytest.skip("demo produced no preview picks")
    eid = str(picks[0].get("espn_id"))
    tip = datetime.fromisoformat(str(picks[0].get("tip")).replace("Z", "+00:00"))
    append_lock(
        {
            "espn_id": eid,
            "event_id": eid,
            "side": "away",
            "market": "spreads",
            "line": -3.5,
            "price": -110,
            "units": 1.0,
            "tip": tip.isoformat(),
            "away_team": picks[0].get("away_team"),
            "home_team": picks[0].get("home_team"),
        },
        path=ledger,
    )
    ledger_data = load_ledger(ledger)
    html = render_ncaam_page_html(
        ledger=ledger_data,
        signals={},
        analytics_head="",
        site_css="",
        updated="Nov 18",
    )
    assert "Morning preview" in html
    assert "NOT official" in html
    assert "Locked" in html
    assert ledger_overlay_status(ledger_data, eid) == "locked"


def test_page_shows_no_longer_qualifies():
    now = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    ledger = {"plays": []}
    picks = [
        {
            "espn_id": "g9",
            "away_team": "Away",
            "home_team": "Home",
            "tip": (now + timedelta(hours=5)).isoformat(),
            "preview_state": PREVIEW_STATE_DROPPED,
            "added_at_et": "Nov 18, 8:00 AM",
            "updated_at_et": "Nov 18, 10:00 AM",
            "side": "away",
            "market": "spreads",
            "line": -1,
            "price": -110,
            "ev": 0.04,
        }
    ]

    def _fake_load(*, et_day=None):
        return {"picks": picks, "last_scan_at_et": "Nov 18, 10:00 AM ET"}

    import sharp_scout.site.ncaam_page as page_mod

    original = page_mod.load_preview
    page_mod.load_preview = _fake_load  # type: ignore[method-assign]
    try:
        html = render_ncaam_page_html(
            ledger=ledger,
            signals={},
            analytics_head="",
            site_css="",
            updated="Nov 18",
        )
    finally:
        page_mod.load_preview = original
    assert "No longer qualifies" in html
    assert "Added Nov 18, 8:00 AM" in html


def test_official_lock_windows_unchanged():
    tip = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)
    assert lock_window(tip - timedelta(minutes=91), tip).value == "too_early"
    assert lock_window(tip - timedelta(minutes=30), tip).value == "primary"
    assert lock_window(tip - timedelta(minutes=20), tip).value == "late"
    assert lock_window(tip - timedelta(minutes=19), tip).value == "missed"


def test_live_ledger_untouched_by_demo_preview():
    before = LEDGER_PATH.read_text() if LEDGER_PATH.exists() else ""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ncaam_ledger.json"
        path.write_text(
            '{"updated_at":"1970-01-01T00:00:00+00:00","starting_units":100,"plays":[],"stage_cards":[],"disagreements":[]}\n'
        )
        run_morning_preview(demo=True, ledger_path=path, build_site=False)
    after = LEDGER_PATH.read_text() if LEDGER_PATH.exists() else ""
    assert before == after