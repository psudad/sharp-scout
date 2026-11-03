#!/usr/bin/env python3
"""Fail loudly when the NCAAM runner is down during today's game window (0 Odds API credits).

Healthy = an ncaam.yml run is in progress, or the committed heartbeat shows a pass in the
last 90 minutes. Only checked from 2h before today's first tip until today's last tip (ET),
using the committed slate file. A missing slate after noon ET in season also fails.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
HEARTBEAT_MAX_AGE = timedelta(minutes=90)
WINDOW_BEFORE_FIRST_TIP = timedelta(hours=2)
SEASON_MONTHS = {11, 12, 1, 2, 3}


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tips(et_day) -> list[datetime] | None:
    p = ROOT / "data" / "ncaam" / f"slate_{et_day:%Y%m%d}.json"
    if not p.exists():
        return None
    try:
        games = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(games, dict):
        games = games.get("games") or []
    return sorted(t for t in (_parse(g.get("commence_time")) for g in games if isinstance(g, dict)) if t)


def _heartbeat() -> tuple[datetime | None, str]:
    p = ROOT / "data" / "ncaam" / "runner_heartbeat.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None, ""
    return _parse(d.get("at")), str(d.get("note") or "")


def _runner_in_progress() -> bool | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    url = f"https://api.github.com/repos/{repo}/actions/workflows/ncaam.yml/runs?status=in_progress&per_page=5"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            runs = json.load(r).get("workflow_runs") or []
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read ncaam.yml runs ({exc})")
        return None
    return any(run.get("event") == "schedule" or run.get("event") == "workflow_dispatch" for run in runs)


def ncaam_stale(now: datetime, tips: list[datetime] | None, hb_at: datetime | None, hb_note: str,
                runner_live: bool | None) -> tuple[bool, str]:
    et_now = now.astimezone(ET)
    if tips is None:
        if et_now.month in SEASON_MONTHS and et_now.hour >= 12:
            return True, f"no NCAAM slate file for {et_now:%Y-%m-%d} after noon ET"
        return False, "no slate yet (before noon ET or out of season)"
    if not tips:
        return False, "no NCAAM games today"
    start, end = tips[0] - WINDOW_BEFORE_FIRST_TIP, tips[-1]
    if not (start <= now <= end):
        return False, "outside today's game window"
    if runner_live:
        return False, "an NCAAM runner is in progress"
    if hb_at and hb_note == "pass" and now - hb_at <= HEARTBEAT_MAX_AGE:
        return False, f"heartbeat fresh ({hb_at.astimezone(ET):%H:%M} ET)"
    hb = f"{hb_at.astimezone(ET):%Y-%m-%d %H:%M} ET ({hb_note})" if hb_at else "none"
    return True, f"no NCAAM runner in progress during the game window; last heartbeat {hb}"


def main() -> int:
    now = datetime.now(timezone.utc)
    tips = _tips(now.astimezone(ET).date())
    hb_at, hb_note = _heartbeat()
    live = _runner_in_progress()
    stale, why = ncaam_stale(now, tips, hb_at, hb_note, live)
    print(f"NCAAM staleness: {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"stale={'true' if stale else 'false'}\n")
    if stale:
        print(f"::error title=NCAAM runner is down::{why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
