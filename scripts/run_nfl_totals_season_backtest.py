#!/usr/bin/env python3
"""Walk-forward 2026 NFL totals season backtest → reports/ CSV + JSON summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nfl.totals.walk_forward import (  # noqa: E402
    append_completed_from_schedules,
    load_games_from_csv,
    run_walk_forward_backtest,
    write_backtest_csv,
)


def main() -> None:
    csv_in = Path("/home/ubuntu/.cursor/projects/workspace/uploads/nfl_totals_every_game_36b2.csv")
    if len(sys.argv) > 1:
        csv_in = Path(sys.argv[1])
    games = load_games_from_csv(csv_in)
    games = append_completed_from_schedules(games, season=2026)
    rows, summary = run_walk_forward_backtest(games, n_sims=5000)
    out_csv = ROOT / "reports" / "nfl_totals_sim_backtest_2026.csv"
    out_json = ROOT / "reports" / "nfl_totals_sim_backtest_2026_summary.json"
    write_backtest_csv(rows, out_csv)
    out_json.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {out_csv} ({len(rows)} games)")


if __name__ == "__main__":
    main()
