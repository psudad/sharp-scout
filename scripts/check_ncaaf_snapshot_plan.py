#!/usr/bin/env python3
"""Exit early in CI when this hour is not a planned NCAAF line-snapshot window."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.scheduler.ncaaf_lines import load_plan, should_run_now  # noqa: E402

PLAN_PATH = ROOT / "data" / "ncaaf_line_plan.json"


def main() -> None:
    now = datetime.now(timezone.utc)
    if not PLAN_PATH.exists():
        print(f"No plan at {PLAN_PATH} — skip (run plan_ncaaf_snapshots.py on Monday)")
        _set_output(False)
        return

    plan = load_plan()
    ok, matched = should_run_now(plan, now=now)
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
