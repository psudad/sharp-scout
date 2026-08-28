#!/usr/bin/env python3
"""Build data/ncaaf_line_plan.json from Odds API kickoffs (college week)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.scheduler.ncaaf_lines import build_line_snapshot_plan, save_plan  # noqa: E402


def main() -> None:
    plan = build_line_snapshot_plan()
    path = save_plan(plan)
    print(
        json.dumps(
            {
                "ok": True,
                "path": str(path),
                "summary": {
                    "week_start": plan.get("week_start"),
                    "week_end": plan.get("week_end"),
                    "n_games": plan["n_games"],
                    "n_runs": plan["n_runs"],
                    "run_hours_by_day": plan.get("run_hours_by_day"),
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
