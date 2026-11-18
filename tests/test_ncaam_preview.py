"""Morning preview — ledger isolation, once-per-day guard, page rendering."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sharp_scout.ledger.tracker import load_ledger, save_ledger
from sharp_scout.ncaam import preview as preview_mod
from sharp_scout.ncaam import preview_store as store_mod
from sharp_scout.ncaam.lock import LEDGER_PATH, append_lock, lock_window
from sharp_scout.ncaam.preview import run_morning_preview
from sharp_scout.ncaam.preview_store import ledger_overlay_status, preview_path_for_day
from sharp_scout.site.ncaam_page import build_ncaam_page, render_ncaam_page_html


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
    monkeypatch.setattr(preview_mod, "NCAAM_LINE_HISTORY_PATH", ncaam_dir / "line_history.json")
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


def test_once_per_day_guard(preview_env):
    _, data, ncaam_dir, _, ledger = preview_env
    now = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    first = run_morning_preview(demo=True, now=now, ledger_path=ledger, build_site=False)
    assert first.get("skipped") is False
    assert preview_path_for_day(now.astimezone(store_mod.ET).date()).exists()
    second = run_morning_preview(demo=True, now=now, ledger_path=ledger, build_site=False)
    assert second.get("skipped") is True
    assert second.get("reason") == "already_ran_today"
    forced = run_morning_preview(
        demo=True, now=now, force=True, manual=True, ledger_path=ledger, build_site=False
    )
    assert forced.get("skipped") is False
    payload = json.loads((data / "ncaam_preview_latest.json").read_text())
    assert payload.get("manual") is True


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