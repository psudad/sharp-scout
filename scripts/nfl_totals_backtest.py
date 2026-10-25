#!/usr/bin/env python3
"""Print NFL totals sim backtest metrics (Weeks 1–6 walk-forward)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nfl.totals.backtest import backtest_from_csv  # noqa: E402


def main() -> None:
    csv = Path("/home/ubuntu/.cursor/projects/workspace/uploads/nfl_totals_every_game_36b2.csv")
    if len(sys.argv) > 1:
        csv = Path(sys.argv[1])
    if not csv.exists():
        print(f"CSV not found: {csv}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(backtest_from_csv(csv, max_week=6), indent=2))


if __name__ == "__main__":
    main()
