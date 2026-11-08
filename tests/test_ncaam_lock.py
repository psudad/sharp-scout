from datetime import datetime, timedelta, timezone

import pytest

from sharp_scout.ledger.tracker import load_ledger, save_ledger
from sharp_scout.ncaam.lock import LockWindow, append_lock, find_play, lock_window


def test_lock_windows_dst_safe():
    tip = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)
    assert lock_window(tip - timedelta(minutes=60), tip) == LockWindow.PRIMARY
    assert lock_window(tip - timedelta(minutes=30), tip) == LockWindow.PRIMARY
    assert lock_window(tip - timedelta(minutes=26), tip) == LockWindow.PRIMARY
    assert lock_window(tip - timedelta(minutes=20), tip) == LockWindow.LATE
    assert lock_window(tip - timedelta(minutes=3), tip) == LockWindow.MISSED
    assert lock_window(tip - timedelta(minutes=120), tip) == LockWindow.TOO_EARLY
    assert lock_window(tip + timedelta(minutes=1), tip) == LockWindow.POST_TIP


def test_lock_window_late_floor_20_min_boundary():
    tip = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)
    assert lock_window(tip - timedelta(minutes=20), tip) == LockWindow.LATE
    assert lock_window(tip - timedelta(minutes=19, seconds=59), tip) == LockWindow.MISSED
    assert lock_window(tip - timedelta(minutes=25, seconds=1), tip) == LockWindow.PRIMARY
    assert lock_window(tip - timedelta(minutes=25), tip) == LockWindow.LATE


def test_refuse_lock_at_or_after_tip(tmp_path):
    path = tmp_path / "ncaam_ledger.json"
    save_ledger({"plays": [], "starting_units": 100, "stage_cards": [], "disagreements": []}, path)
    tip = datetime.now(timezone.utc) - timedelta(minutes=1)
    with pytest.raises(ValueError):
        append_lock({"espn_id": "1", "tip": tip.isoformat(), "side": "home", "market": "spreads"}, path=path)


def test_immutable_after_lock(tmp_path):
    path = tmp_path / "ncaam_ledger.json"
    save_ledger({"plays": [], "starting_units": 100, "stage_cards": [], "disagreements": []}, path)
    tip = datetime.now(timezone.utc) + timedelta(hours=2)
    append_lock(
        {
            "espn_id": "e1",
            "event_id": "e1",
            "side": "away",
            "market": "spreads",
            "line": 6.5,
            "price": -110,
            "units": 1.0,
            "tip": tip.isoformat(),
        },
        path=path,
    )
    ledger = load_ledger(path)
    play = find_play(ledger, "e1")
    assert play and play.get("locked_at")
    append_lock(
        {
            "espn_id": "e1",
            "event_id": "e1",
            "side": "home",
            "market": "spreads",
            "line": -6.5,
            "price": -110,
            "units": 99,
            "tip": tip.isoformat(),
        },
        path=path,
    )
    ledger2 = load_ledger(path)
    play2 = find_play(ledger2, "e1")
    assert play2["side"] == "away"
    assert play2["units"] == 1.0
