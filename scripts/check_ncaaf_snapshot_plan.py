#!/usr/bin/env python3
"""Exit early in CI when this hour is not a planned NCAAF line-snapshot window."""

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
    should_run_now,
)

PLAN_PATH = ROOT / "data" / "ncaaf_line_plan.json"
STATE_PATH = ROOT / "data" / "ncaaf_rebuild_state.json"
# Min gap between full rebuilds. The cron runs every 15 min so a window is never
# missed to drift, but we only rebuild the board (and hit the Odds API) this often.
REBUILD_THROTTLE_MINUTES = 45


def _last_rebuild() -> datetime | None:
    if not STATE_PATH.exists():
        return None
    try:
        ts = json.loads(STATE_PATH.read_text()).get("last_rebuild")
        dt = datetime.fromisoformat(ts) if ts else None
    except (ValueError, OSError):
        return None
    if dt and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main() -> None:
    now = datetime.now(timezone.utc)
    if not PLAN_PATH.exists():
        print(f"No plan at {PLAN_PATH} — skip (run plan_ncaaf_snapshots.py on Monday)")
        _set_output(False, False)
        return

    plan = load_plan()
    ok, matched = should_run_now(plan, now=now)
    in_zone, rebuild_hits = rebuild_due(plan, now=now)
    last = _last_rebuild()
    throttled = last is not None and (now - last) < timedelta(minutes=REBUILD_THROTTLE_MINUTES)
    do_rebuild = in_zone and not throttled
    if ok:
        print(f"Planned NCAAF line snapshot(s) due: {len(matched)}")
        for m in matched[:8]:
            kind = m.get("kind")
            if kind == "open":
                print(f"  OPEN weekly board @ {m.get('run_at')}")
            elif kind == "open_early":
                print(f"  OPEN early (Sunday) board @ {m.get('run_at')}")
            else:
                print(
                    f"  {m.get('matchup')} T-{m.get('window_hours')}h "
                    f"kickoff {m.get('kickoff')}"
                )
    else:
        tol = plan.get("tolerance_minutes", 25)
        print(f"No planned snapshot within ±{tol} min of {now.isoformat()}")

    if in_zone:
        n = len(rebuild_hits)
        if do_rebuild:
            print(f"Full board rebuild: {n} game(s) inside the pregame zone (T≤3h)")
        else:
            print(f"In pregame zone ({n} game(s)) but throttled — last rebuild {last.isoformat()}")

    _set_output(ok or do_rebuild, do_rebuild)


def _set_output(run: bool, rebuild: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if run else 'false'}\n")
            fh.write(f"rebuild={'true' if rebuild else 'false'}\n")
    if not run:
        sys.exit(0)


if __name__ == "__main__":
    main()
