#!/usr/bin/env python3
"""Lightweight CI gate: run a full NCAAF board refresh if last_rebuild is stale on a game day."""

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

STATE_PATH = ROOT / "data" / "ncaaf_rebuild_state.json"
PLAN_PATH = ROOT / "data" / "ncaaf_line_plan.json"

STALE_AFTER = timedelta(hours=2)
# Align with check_ncaaf_snapshot_plan — avoids duplicate full runs when crons cluster.
REBUILD_THROTTLE = timedelta(minutes=45)
# ncaaf.yml backup slots (+25 / +50 min after primary): skip if primary already refreshed.
BACKUP_MIN_AGE = timedelta(minutes=20)


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


def last_rebuild_at() -> datetime | None:
    """Authoritative full-board refresh time (written by every full NCAAF CI path)."""
    if not STATE_PATH.exists():
        return None
    try:
        ts = json.loads(STATE_PATH.read_text()).get("last_rebuild")
        return _parse_ts(ts)
    except (OSError, json.JSONDecodeError):
        return None


def needs_pipeline_backup_refresh(
    *,
    now: datetime | None = None,
    min_age: timedelta = BACKUP_MIN_AGE,
) -> bool:
    """True when a scheduled ncaaf.yml *backup* slot should run (primary did not refresh recently)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    last = last_rebuild_at()
    if last is None:
        print("No last_rebuild — backup slot will run")
        return True
    age = now - last
    if age >= min_age:
        print(f"last_rebuild {last.isoformat()} is {age.total_seconds() / 60:.0f}m old — backup runs")
        return True
    print(f"last_rebuild {last.isoformat()} is fresh ({age.total_seconds() / 60:.0f}m ago) — skip backup")
    return False


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

    last = last_rebuild_at()
    if last is None:
        print("No last_rebuild — stale by default")
        stale = True
    else:
        age = now - last
        stale = age > STALE_AFTER
        print(f"last_rebuild {last.isoformat()} ({age.total_seconds() / 3600:.2f}h ago)")

    if not stale:
        print(f"Board fresh (≤ {STALE_AFTER.total_seconds() / 3600:g}h since last_rebuild) — skip")
        return False

    if last is not None and (now - last) < REBUILD_THROTTLE:
        print(f"Throttled — last_rebuild {last.isoformat()} ({(now - last).total_seconds() / 60:.0f}m ago)")
        return False

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
