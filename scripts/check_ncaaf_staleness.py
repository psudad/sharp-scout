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
# ncaaf.yml: skip a delayed primary if a backup (or other run) refreshed recently.
PRIMARY_SLOT_RECENT = timedelta(minutes=40)
# Backups skip when last_rebuild is at/after (nominal primary UTC − slack).
PRIMARY_SLOT_SLACK = timedelta(minutes=5)

# Backup cron → nominal primary fire (hour, minute) UTC for the same calendar day.
BACKUP_TO_PRIMARY_UTC: dict[str, tuple[int, int]] = {
    "32 15 * * 1-6": (15, 7),
    "57 15 * * 1-6": (15, 7),
    "48 18 * * 6": (18, 23),
    "13 19 * * 6": (18, 23),
    "32 22 * * 5,6": (22, 7),
    "57 22 * * 5,6": (22, 7),
    "32 12 * * 0": (12, 7),
    "57 12 * * 0": (12, 7),
}


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


def _github_utc_dow(dt: datetime) -> int:
    return (dt.weekday() + 1) % 7


def _cron_dow_matches(dt: datetime, dow_field: str) -> bool:
    if dow_field == "*":
        return True
    allowed: set[int] = set()
    for part in dow_field.split(","):
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            allowed.update(range(int(start_s), int(end_s) + 1))
        else:
            allowed.add(int(part))
    return _github_utc_dow(dt) in allowed


def nominal_primary_utc_for_backup(backup_cron: str, now: datetime) -> datetime | None:
    """Today's nominal primary UTC time for this backup line, or None if DOW does not match."""
    backup_cron = backup_cron.strip()
    hm = BACKUP_TO_PRIMARY_UTC.get(backup_cron)
    if hm is None:
        return None
    parts = backup_cron.split()
    if len(parts) != 5:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if not _cron_dow_matches(now, parts[4]):
        return None
    hour, minute = hm
    return datetime(now.year, now.month, now.day, hour, minute, tzinfo=timezone.utc)


def should_run_primary_slot(
    *,
    cron: str,
    now: datetime | None = None,
) -> bool:
    """False when GitHub starts a primary late but a rebuild already happened (e.g. backup)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    last = last_rebuild_at()
    if last is not None and (now - last) < PRIMARY_SLOT_RECENT:
        print(
            f"Primary skip: last_rebuild {last.isoformat()} "
            f"({(now - last).total_seconds() / 60:.0f}m ago, within {PRIMARY_SLOT_RECENT.total_seconds() / 60:.0f}m)"
        )
        return False
    return True


def needs_pipeline_backup_refresh(
    *,
    now: datetime | None = None,
    backup_cron: str,
) -> bool:
    """True when no rebuild since this window's nominal primary time (± slack)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    primary_at = nominal_primary_utc_for_backup(backup_cron, now)
    if primary_at is None:
        print(f"Backup cron {backup_cron!r} does not apply today — skip")
        return False
    cutoff = primary_at - PRIMARY_SLOT_SLACK
    last = last_rebuild_at()
    if last is None:
        print(f"No last_rebuild — backup {backup_cron!r} runs (primary was {primary_at.isoformat()})")
        return True
    if last >= cutoff:
        print(
            f"Backup skip: last_rebuild {last.isoformat()} >= primary window start {cutoff.isoformat()} "
            f"(nominal primary {primary_at.isoformat()})"
        )
        return False
    print(
        f"Backup run: last_rebuild {last.isoformat()} before primary window {cutoff.isoformat()} "
        f"(nominal primary {primary_at.isoformat()})"
    )
    return True


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
