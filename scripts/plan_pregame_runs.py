#!/usr/bin/env python3
"""Build data/pregame_run_plan.json from nflverse schedule (+ Odds API kickoffs)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.scheduler.plan import build_run_plan, save_plan  # noqa: E402


def main() -> None:
    plan = build_run_plan()
    path = save_plan(plan)
    print(json.dumps({"ok": True, "path": str(path), "summary": {
        "n_games": plan["n_games"],
        "n_runs": plan["n_runs"],
        "run_hours_by_day": plan.get("run_hours_by_day"),
    }}, indent=2))


if __name__ == "__main__":
    main()
