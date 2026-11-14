"""Regression tests for the PR #141 review fixes (rules, budget, runner safety)."""

import json
from datetime import date, datetime, timedelta, timezone

from sharp_scout.ncaam import credits as credits_mod
from sharp_scout.ncaam import runner as runner_mod
from sharp_scout.ncaam.candidates import pick_best_per_game
from sharp_scout.ncaam.rules import apply_daily_cap, price_qualifies


def test_moneyline_only_between_minus150_and_plus200():
    assert price_qualifies(150, market="h2h")
    assert price_qualifies(-150, market="h2h")
    assert not price_qualifies(250, market="h2h")
    assert not price_qualifies(-160, market="h2h")
    assert price_qualifies(-110, market="spreads")
    assert not price_qualifies(-155, market="spreads")


def test_spread_preferred_over_ml_for_same_game():
    cands = [
        {"espn_id": "1", "market": "h2h", "ev": 0.09, "hook_score": 0},
        {"espn_id": "1", "market": "spreads", "ev": 0.04, "hook_score": 0},
    ]
    assert pick_best_per_game(cands)["1"]["market"] == "spreads"
    only_ml = [{"espn_id": "2", "market": "h2h", "ev": 0.05, "hook_score": 0}]
    assert pick_best_per_game(only_ml)["2"]["market"] == "h2h"


def test_daily_cap_removed_posts_all_qualifying():
    day = date(2026, 11, 2)
    cands = [
        {"event_id": str(i), "espn_id": str(i), "ev": 0.05, "et_day": day.isoformat(), "side": "home", "line": -3.0}
        for i in range(5)
    ]
    # Cap removed: earlier locks do not block new qualifying picks.
    assert len(apply_daily_cap(cands, et_day=day, already_plays=8, already_units=8.0)) == 5
    picked = apply_daily_cap(cands, et_day=day, already_plays=6, already_units=6.0)
    assert len(picked) == 5
    assert all(p["units"] == 1.0 for p in picked)


def test_budget_floor_uses_last_recorded_remaining(tmp_path, monkeypatch):
    monkeypatch.setattr(credits_mod, "NCAAM_DATA", tmp_path)
    credits_mod.record_spend(2, remaining_header=40)
    skip, reason = credits_mod.should_skip_snapshot(remaining_header=None)
    assert skip and reason == "global_remaining_floor"


def test_heartbeat_exited_is_not_live(tmp_path, monkeypatch):
    hb = tmp_path / "hb.json"
    monkeypatch.setattr(runner_mod, "HEARTBEAT_PATH", hb)
    runner_mod.write_heartbeat(runner_id="a", note="pass")
    assert runner_mod.another_runner_live()
    runner_mod.write_heartbeat(runner_id="a", note=runner_mod.EXITED_NOTE)
    assert not runner_mod.another_runner_live()


def test_loop_never_sleeps_past_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "HEARTBEAT_PATH", tmp_path / "hb.json")
    monkeypatch.setattr(runner_mod, "run_pass", lambda **kw: {})
    slept: list[float] = []
    clock = {"t": datetime(2026, 11, 2, 15, tzinfo=timezone.utc)}

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["t"]

    def fake_sleep(s):
        slept.append(s)
        clock["t"] = clock["t"] + timedelta(seconds=s)

    monkeypatch.setattr(runner_mod, "datetime", FakeDT)
    monkeypatch.setattr(runner_mod.time, "sleep", fake_sleep)
    # budget 2 min, pass every 15: must not sleep 15 min.
    runner_mod.run_loop(demo=False, pass_every_min=15, budget_min=2)
    assert slept and max(slept) <= 120
    assert sum(slept) <= 120
    assert json.loads((tmp_path / "hb.json").read_text())["note"] == runner_mod.EXITED_NOTE


def test_no_snapshot_when_no_games_near_lock():
    now = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
    rows = [{"commence_time": now + timedelta(hours=5)}, {"commence_time": now - timedelta(hours=1)}]
    assert runner_mod._games_near_lock(rows, now) == 0
    rows.append({"commence_time": now + timedelta(minutes=60)})
    assert runner_mod._games_near_lock(rows, now) == 1
    rows.append({"commence_time": now + timedelta(minutes=15)})
    assert runner_mod._games_near_lock(rows, now) == 1


def test_publish_pass_heartbeat_only_without_locks(monkeypatch):
    calls: list[tuple[str, bool, list[str]]] = []

    def fake_push(message, *, trigger_pages=True, add_paths=None):
        calls.append((message, trigger_pages, list(add_paths or [])))
        return True

    monkeypatch.setattr(runner_mod, "_git_commit_push", fake_push)
    # Isolate from a real ratings_fetch_failed_YYYYMMDD.json on the repo checkout.
    monkeypatch.setattr(runner_mod, "daily_fetch_state_paths_for_commit", lambda: [])
    assert runner_mod.publish_pass(new_locks=False, runner_id="r1")
    assert len(calls) == 1
    msg, trigger, paths = calls[0]
    assert msg == "chore(ncaam): runner heartbeat"
    assert trigger is False
    assert paths == runner_mod.HEARTBEAT_COMMIT_PATHS


def test_publish_pass_full_board_on_locks(monkeypatch):
    calls: list[tuple[str, bool]] = []

    def fake_push(message, *, trigger_pages=True, add_paths=None):
        calls.append((message, trigger_pages))
        return True

    monkeypatch.setattr(runner_mod, "_git_commit_push", fake_push)
    runner_mod.publish_pass(new_locks=True)
    assert calls == [("chore(ncaam): lock picks", True)]


def test_publish_pass_failure_sets_stuck_note(tmp_path, monkeypatch):
    hb = tmp_path / "hb.json"
    monkeypatch.setattr(runner_mod, "HEARTBEAT_PATH", hb)
    monkeypatch.setattr(runner_mod, "_git_commit_push", lambda *a, **k: False)
    assert not runner_mod.publish_pass(new_locks=True, runner_id="r1")
    data = json.loads(hb.read_text())
    assert data["note"] == "stuck:publish_failed"
    assert data["last_publish_ok"] is False
