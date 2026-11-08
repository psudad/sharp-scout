"""Regression tests for NCAAM git publish path (heartbeat, locks, Pages, recovery)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sharp_scout.ledger.tracker import load_ledger, save_ledger
from sharp_scout.ncaam import runner as runner_mod
from sharp_scout.ncaam.lock import LockWindow, lock_window
from sharp_scout.ncaam.runner import NCAAM_COMMIT_PATHS, restore_from_backup


@pytest.fixture
def ncaam_paths(tmp_path, monkeypatch):
    data = tmp_path / "data"
    ncaam_dir = data / "ncaam"
    ncaam_dir.mkdir(parents=True)
    docs = tmp_path / "docs"
    docs.mkdir()
    ledger = data / "ncaam_ledger.json"
    ledger.write_text(
        '{"updated_at":"1970-01-01T00:00:00+00:00","starting_units":100,"plays":[],"stage_cards":[],"disagreements":[]}\n'
    )
    hb = ncaam_dir / "runner_heartbeat.json"
    monkeypatch.setattr(runner_mod, "HEARTBEAT_PATH", hb)
    monkeypatch.setattr(runner_mod, "LEDGER_PATH", ledger)
    from sharp_scout.ncaam import lock as lock_mod

    monkeypatch.setattr(lock_mod, "LEDGER_PATH", ledger)
    import sharp_scout.config as config_mod

    monkeypatch.setattr(config_mod, "ROOT", tmp_path)
    monkeypatch.setattr(runner_mod, "ROOT", tmp_path)
    monkeypatch.setattr(runner_mod, "DATA_DIR", data)
    return tmp_path, hb, ledger, ncaam_dir, docs


def test_needs_full_publish_retries_after_failed_push(ncaam_paths):
    _, hb, _, _, _ = ncaam_paths
    hb.write_text(
        json.dumps(
            {"runner_id": "r1", "at": "2026-11-08T20:00:00+00:00", "note": "stuck:publish_failed", "last_publish_ok": False}
        )
        + "\n"
    )
    assert runner_mod._needs_full_publish(new_locks=False) is True


def test_publish_heartbeat_only_when_publish_ok_and_no_new_locks(ncaam_paths, monkeypatch):
    _, hb, _, _, _ = ncaam_paths
    hb.write_text(json.dumps({"runner_id": "r1", "at": "2026-11-08T20:00:00+00:00", "note": "pass", "last_publish_ok": True}) + "\n")
    staged: list[list[str] | None] = []

    def fake_push(message, *, trigger_pages=True, add_paths=None):
        staged.append(list(add_paths or []))
        return True

    monkeypatch.setattr(runner_mod, "_git_commit_push", fake_push)
    assert runner_mod.publish_pass(new_locks=False, runner_id="r1")
    assert staged == [runner_mod.HEARTBEAT_COMMIT_PATHS]


def test_publish_lock_uses_full_paths_and_pages(ncaam_paths, monkeypatch):
    _, _, _, ncaam_dir, docs = ncaam_paths
    sharp = ncaam_dir / "sharp3_ledger.json"
    sharp.write_text('{"plays":[{"id":"lab1","status":"pending"}]}\n')
    (docs / "ncaam.html").write_text("<html>board</html>\n")
    captured: list[tuple[bool, list[str]]] = []

    def fake_push(message, *, trigger_pages=True, add_paths=None):
        captured.append((trigger_pages, list(add_paths or [])))
        return True

    monkeypatch.setattr(runner_mod, "_git_commit_push", fake_push)
    assert runner_mod.publish_pass(new_locks=True, runner_id="r1")
    assert captured == [(True, NCAAM_COMMIT_PATHS)]


def test_publish_failure_then_retry_without_new_locks_still_full(ncaam_paths, monkeypatch):
    _, hb, ledger, ncaam_dir, _ = ncaam_paths
    tip = datetime.now(timezone.utc) + timedelta(hours=2)
    save_ledger(
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "starting_units": 100,
            "plays": [
                {
                    "id": "p1",
                    "espn_id": "e1",
                    "event_id": "e1",
                    "status": "pending",
                    "side": "away",
                    "market": "spreads",
                    "line": 5.5,
                    "price": -110,
                    "units": 1.0,
                    "locked_at": datetime.now(timezone.utc).isoformat(),
                    "tip": tip.isoformat(),
                }
            ],
            "stage_cards": [],
            "disagreements": [],
        },
        ledger,
    )
    attempts: list[tuple[bool, list[str]]] = []

    def fake_push(message, *, trigger_pages=True, add_paths=None):
        attempts.append((trigger_pages, list(add_paths or [])))
        return len(attempts) > 1

    monkeypatch.setattr(runner_mod, "_git_commit_push", fake_push)
    assert not runner_mod.publish_pass(new_locks=True, runner_id="r1")
    assert attempts[0][0] is True and attempts[0][1] == NCAAM_COMMIT_PATHS
    assert json.loads(hb.read_text())["last_publish_ok"] is False

    assert runner_mod.publish_pass(new_locks=False, runner_id="r1")
    assert len(attempts) == 2
    assert attempts[1][0] is True and attempts[1][1] == NCAAM_COMMIT_PATHS
    assert json.loads(hb.read_text())["last_publish_ok"] is True


def test_dispatch_pages_failure_surfaces(ncaam_paths, monkeypatch):
    script = ncaam_paths[0] / "scripts" / "ci_git_push_retry.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\nexit 0\n")
    script.chmod(0o755)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GH_TOKEN", "test-token")

    def fail_gh(*_a, **_k):
        return subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="403 forbidden")

    monkeypatch.setattr(runner_mod.subprocess, "run", fail_gh)
    assert not runner_mod._dispatch_pages_workflow()


def test_git_push_calls_dispatch_when_pages_enabled(ncaam_paths, monkeypatch):
    root = ncaam_paths[0]
    script = root / "scripts" / "ci_git_push_retry.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/bash\nexit 0\n")
    script.chmod(0o755)
    calls: list[list[str]] = []

    def track_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if cmd[0] == "bash":
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GH_TOKEN", "tok")
    monkeypatch.setattr(runner_mod.subprocess, "run", track_run)
    assert runner_mod._git_commit_push("test", trigger_pages=True, add_paths=runner_mod.HEARTBEAT_COMMIT_PATHS)
    assert any(c[:3] == ["gh", "workflow", "run"] for c in calls)


def test_restore_from_backup_keeps_official_and_sharp_ledgers(ncaam_paths, monkeypatch):
    _, _, ledger, ncaam_dir, _ = ncaam_paths
    backup = ncaam_paths[0] / "backup"
    (backup / "data/ncaam").mkdir(parents=True)
    (backup / "data/ncaam/sharp3_ledger.json").write_text('{"plays":[{"id":"sharp"}]}\n')
    (backup / "data/ncaam/sharp35_ledger.json").write_text('{"plays":[{"id":"s35"}]}\n')
    tip = datetime.now(timezone.utc) + timedelta(hours=1)
    save_ledger(
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "starting_units": 100,
            "plays": [
                {
                    "id": "official",
                    "espn_id": "e9",
                    "event_id": "e9",
                    "status": "pending",
                    "side": "home",
                    "market": "spreads",
                    "line": -3.0,
                    "price": -110,
                    "units": 1.0,
                    "locked_at": datetime.now(timezone.utc).isoformat(),
                    "tip": tip.isoformat(),
                }
            ],
            "stage_cards": [],
            "disagreements": [],
        },
        backup / "data/ncaam_ledger.json",
    )
    save_ledger({"plays": [], "starting_units": 100, "stage_cards": [], "disagreements": []}, ledger)
    assert not load_ledger(ledger).get("plays")

    restore_from_backup(backup)
    official = load_ledger(ledger)
    assert official["plays"] and official["plays"][0]["id"] == "official"
    assert json.loads((ncaam_dir / "sharp3_ledger.json").read_text())["plays"][0]["id"] == "sharp"
    assert json.loads((ncaam_dir / "sharp35_ledger.json").read_text())["plays"][0]["id"] == "s35"


def test_sharp_systems_share_t20_lock_window_with_new_system():
    """Lab Sharp 3/3.5 use the same lock_window helper — late floor is T-20 for all."""
    tip = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)
    assert lock_window(tip - timedelta(minutes=20), tip) == LockWindow.LATE
    assert lock_window(tip - timedelta(minutes=19, seconds=59), tip) == LockWindow.MISSED


def test_ncaam_workflow_declares_actions_write():
    yml = (Path(__file__).resolve().parents[1] / ".github/workflows/ncaam.yml").read_text()
    assert "actions: write" in yml
    assert "GH_TOKEN: ${{ github.token }}" in yml
