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
from sharp_scout.ncaam.preview_store import (
    is_open_preview_pick,
    ledger_overlay_status,
    open_preview_picks,
    preview_path_for_day,
)
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


def test_preview_leaves_price_edge_diagnostics_unchanged(preview_env, monkeypatch):
    from sharp_scout.ncaam import price_edge_diagnostics as diag_mod

    _, data, _, _, ledger = preview_env
    shadow = data / "shadow" / "ncaam_price_edge_diagnostics.json"
    shadow.parent.mkdir(parents=True, exist_ok=True)
    marker = '{"updated_at":"fixture","entries":[{"espn_id":"official-only"}]}\n'
    shadow.write_text(marker)
    monkeypatch.setattr(diag_mod, "SHADOW_PATH", shadow)

    def _forbid(*_a, **_k):
        raise AssertionError("preview must not record price-edge diagnostics")

    monkeypatch.setattr(diag_mod, "record_price_edge_batch", _forbid)
    now = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    run_morning_preview(demo=True, now=now, ledger_path=ledger, build_site=False)
    assert shadow.read_text() == marker


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


def _base_pick(*, now: datetime, espn_id: str = "g1", hours_ahead: float = 5) -> dict:
    tip = now + timedelta(hours=hours_ahead)
    return {
        "espn_id": espn_id,
        "event_id": espn_id,
        "away_team": "Away",
        "home_team": "Home",
        "tip": tip.isoformat(),
        "preview_state": PREVIEW_STATE_ACTIVE,
        "added_at_et": "Nov 18, 8:00 AM",
        "updated_at_et": "Nov 18, 10:00 AM",
        "side": "away",
        "market": "spreads",
        "line": -1,
        "price": -110,
        "ev": 0.04,
    }


def test_open_preview_visible_filter_cases():
    now = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    ledger = {"plays": []}
    open_pick = _base_pick(now=now, espn_id="open1")
    assert is_open_preview_pick(open_pick, ledger, now=now)

    dropped = {**open_pick, "espn_id": "drop1", "preview_state": PREVIEW_STATE_DROPPED}
    assert not is_open_preview_pick(dropped, ledger, now=now)

    yesterday_tip = datetime(2026, 11, 17, 23, 0, tzinfo=timezone.utc)
    old_day = {**open_pick, "espn_id": "old1", "tip": yesterday_tip.isoformat()}
    assert not is_open_preview_pick(old_day, ledger, now=now)

    locked_tip = datetime.fromisoformat(open_pick["tip"].replace("Z", "+00:00"))
    ledger_locked = {
        "plays": [
            {
                "espn_id": "lock1",
                "side": "away",
                "status": "pending",
                "market": "spreads",
                "locked_at": now.isoformat(),
            }
        ]
    }
    locked_pick = {**open_pick, "espn_id": "lock1", "event_id": "lock1", "tip": locked_tip.isoformat()}
    assert not is_open_preview_pick(locked_pick, ledger_locked, now=now)

    ledger_pass = {
        "plays": [
            {
                "espn_id": "pass1",
                "side": "",
                "status": "no_play",
                "market": "spreads",
                "locked_at": now.isoformat(),
            }
        ]
    }
    passed_pick = {**open_pick, "espn_id": "pass1", "event_id": "pass1"}
    assert not is_open_preview_pick(passed_pick, ledger_pass, now=now)

    # Inside lock window (T-30) preview section should hide even if state is still active in JSON.
    near_tip = now + timedelta(minutes=30)
    in_window = {**open_pick, "espn_id": "win1", "tip": near_tip.isoformat()}
    assert not is_open_preview_pick(in_window, ledger, now=now)


def test_page_renders_only_open_previews(preview_env):
    tmp_path, data, ncaam_dir, docs, ledger = preview_env
    now = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    open_pick = _base_pick(now=now, espn_id="visible")
    closed_pick = {**_base_pick(now=now, espn_id="closed"), "preview_state": PREVIEW_STATE_DROPPED}
    yesterday = {**_base_pick(now=now, espn_id="yesterday"), "tip": (now - timedelta(days=1)).isoformat()}
    payload = {
        "picks": [open_pick, closed_pick, yesterday],
        "last_scan_at_et": "Nov 18, 10:00 AM ET",
    }
    (data / "ncaam_preview_latest.json").write_text(json.dumps(payload))

    def _fake_load(*, et_day=None):
        return payload

    import sharp_scout.site.ncaam_page as page_mod

    original = page_mod.load_preview
    page_mod.load_preview = _fake_load  # type: ignore[method-assign]
    try:
        html = render_ncaam_page_html(
            ledger={"plays": []},
            signals={},
            analytics_head="",
            site_css="",
            updated="Nov 18",
            preview_html=None,
            now=now,
        )
    finally:
        page_mod.load_preview = original

    assert "Morning preview" in html
    assert "Away @ Home" in html
    assert html.count('preview-status open">Preview</span>') == 1
    assert "No longer qualifies" not in html
    assert open_preview_picks(payload["picks"], {"plays": []}, now=now) == [open_pick]


def test_page_hides_preview_when_locked_pick_exists(preview_env):
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
        preview_html=None,
        now=now,
    )
    assert ledger_overlay_status(ledger_data, eid) == "locked"
    assert "ncaam-preview" not in html or "Morning preview" not in html
    assert "LOCKED" in html


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