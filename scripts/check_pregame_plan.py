#!/usr/bin/env python3
"""Exit early in CI when this hour is not a planned pregame window (stdlib only)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data" / "pregame_run_plan.json"
DEFAULT_TOLERANCE_MIN = 25


def should_run(plan: dict, now: datetime) -> tuple[bool, list[dict]]:
    tolerance = plan.get("tolerance_minutes", DEFAULT_TOLERANCE_MIN)
    tol = timedelta(minutes=tolerance)
    catchup = plan.get("catchup", os.environ.get("PREGAME_CATCHUP", "true").lower() != "false")
    lookback = timedelta(hours=float(plan.get("catchup_hours", 6)))
    matched: list[dict] = []
    for r in plan.get("runs") or []:
        try:
            run_at = datetime.fromisoformat(r["run_at"])
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        kickoff = None
        try:
            kickoff = datetime.fromisoformat(r["kickoff"]) if r.get("kickoff") else None
            if kickoff is not None and kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=timezone.utc)
        except ValueError:
            kickoff = None
        if abs(now - run_at) <= tol:
            matched.append(r)
        elif (
            catchup
            and run_at < now <= run_at + lookback
            and kickoff is not None
            and now < kickoff
        ):
            # Missed window (cron drift): run late; fired-state dedupes in the pipeline.
            matched.append(r)
    return bool(matched), matched


def main() -> None:
    now = datetime.now(timezone.utc)
    if not PLAN_PATH.exists():
        print(f"No plan at {PLAN_PATH} — skip run (build plan on Monday or run plan_pregame_runs.py)")
        _set_output(False)
        return

    plan = json.loads(PLAN_PATH.read_text())
    ok, matched = should_run(plan, now)
    if ok:
        print(f"Planned pregame window(s) due: {len(matched)}")
        for m in matched[:5]:
            print(f"  {m.get('matchup')} T-{m.get('window_hours')}h kickoff {m.get('kickoff')}")
    else:
        print(f"No planned run within ±{plan.get('tolerance_minutes', DEFAULT_TOLERANCE_MIN)} min of {now.isoformat()}")

    _set_output(ok)


def _set_output(run: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if run else 'false'}\n")
    if not run:
        sys.exit(0)


if __name__ == "__main__":
    main()
