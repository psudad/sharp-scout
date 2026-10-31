#!/usr/bin/env python3
"""Lightweight CI gate: run a full NCAAF board refresh if signals are stale on a game day."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.scheduler.ncaaf_lines import (  # noqa: E402
    load_plan,
    rebuild_due,
)
from sharp_scout.utils.slate import parse_commence  # noqa: E402

SIGNALS_PATH = ROOT / "docs" / "latest_ncaaf_signals.json"
STATE_PATH = ROOT / "data" / "ncaaf_rebuild_state.json"
PLAN_PATH = ROOT / "data" / "ncaaf_line_plan.json"

STALE_AFTER = timedelta(hours=2)
# Align with check_ncaaf_snapshot_plan — avoids duplicate full runs when crons cluster.
REBUILD_THROTTLE = timedelta(minutes=45)


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _last_full_run() -> datetime | None:
    candidates: list[datetime] = []
    if SIGNALS_PATH.exists():
        try:
            ts = json.loads(SIGNALS_PATH.read_text()).get("generated_at")
            if parsed := _parse_ts(ts):
                candidates.append(parsed)
        except (OSError, json.JSONDecodeError):
            pass
    if STATE_PATH.exists():
        try:
            ts = json.loads(STATE_PATH.read_text()).get("last_rebuild")
            if parsed := _parse_ts(ts):
                candidates.append(parsed)
        except (OSError, json.JSONDecodeError):
            pass
    return max(candidates) if candidates else None


def _kickoffs_today_et(plan: dict, now: datetime) -> bool:
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    today = now.astimezone(et).date()
    for g in plan.get("games") or []:
        kickoff = parse_commence(g.get("kickoff"))
        if kickoff is None:
            continue
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        if kickoff.astimezone(et).date() == today:
            return True
    return False


def _is_ncaaf_gameday(plan: dict, now: datetime) -> bool:
    if not plan:
        return False
    in_zone, _ = rebuild_due(plan, now=now)
    if in_zone:
        return True
    return _kickoffs_today_et(plan, now)


def should_run_full_refresh(*, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    plan = load_plan() if PLAN_PATH.exists() else {}

    if not _is_ncaaf_gameday(plan, now):
        print("Not an NCAAF game day (no kickoffs today ET, not in pregame zone) — skip")
        return False

    last = _last_full_run()
    if last is None:
        print("No prior full-run timestamp — stale by default")
        stale = True
    else:
        age = now - last
        stale = age > STALE_AFTER
        print(f"Last full run {last.isoformat()} ({age.total_seconds() / 3600:.2f}h ago)")

    if not stale:
        print(f"Signals fresh (≤ {STALE_AFTER.total_seconds() / 3600:g}h) — skip")
        return False

    if STATE_PATH.exists():
        try:
            rb = _parse_ts(json.loads(STATE_PATH.read_text()).get("last_rebuild"))
            if rb and (now - rb) < REBUILD_THROTTLE:
                print(f"Throttled — rebuild {rb.isoformat()} ({(now - rb).total_seconds() / 60:.0f}m ago)")
                return False
        except (OSError, json.JSONDecodeError):
            pass

    print("Stale NCAAF board on game day — full run warranted")
    return True


def main() -> None:
    _set_output(should_run_full_refresh())


def _set_output(run: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if run else 'false'}\n")
    if not run:
        sys.exit(0)


if __name__ == "__main__":
    main()
