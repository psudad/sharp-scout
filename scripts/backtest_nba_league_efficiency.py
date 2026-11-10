#!/usr/bin/env python3
"""Backtest league efficiency re-centering (research only)."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from nba_pace_projection_backtest_lib import (  # noqa: E402
    ESPN_LINES_PATH,
    format_backtest_table,
    run_projection_backtest,
    season_bounds,
)
from sharp_scout.config import DATA_DIR  # noqa: E402


def _run_with_flag(enabled: bool, **kwargs):
    key = "NBA_LEAGUE_EFFICIENCY_CORRECTION_ENABLED"
    prev = os.environ.get(key)
    os.environ[key] = "true" if enabled else "false"
    from sharp_scout.config import get_settings

    get_settings.cache_clear()
    try:
        return run_projection_backtest(**kwargs)
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        get_settings.cache_clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper", type=Path, default=DATA_DIR / "paper" / "nba_score_model.json")
    parser.add_argument("--espn-lines", type=Path, default=ESPN_LINES_PATH)
    parser.add_argument(
        "--season",
        action="append",
        default=[],
        help="Season label e.g. 2025-26 (repeatable); default 2025-26 and 2026-27 YTD",
    )
    args = parser.parse_args()

    seasons = args.season or ["2025-26", "2026-27"]
    today = date.today()

    print(
        "## Lines\n"
        "- **Repo**: merged pre-tip Odds API scans in `nba_score_model.json` where graded.\n"
        "- **ESPN pickcenter backfill** (`nba_espn_pregame_lines.json`): used when no repo line; "
        "typically near-close DraftKings, not T−1h consensus.\n"
        "- **Scores**: ESPN finals via walk-forward `engine_at_start_of_et_date` (real box scores).\n"
    )

    for season in seasons:
        start, end = season_bounds(season)
        through = min(end, today)
        if through < start:
            continue
        kw = dict(
            season_start=start,
            through=through,
            paper_path=args.paper,
            espn_lines_path=args.espn_lines,
        )
        before = _run_with_flag(False, label="before", **kw)
        after = _run_with_flag(True, label="after", **kw)

        print(f"\n### Season {season} (through {through.isoformat()} ET)\n")
        print(format_backtest_table(before, after))
        if season == "2025-26" and after["all_games_projection"].get("mean_bias", 0) > before["all_games_projection"].get(
            "mean_bias", 0
        ):
            print(
                "\n**Note:** Correction did not improve mean bias on 2025-26 in this replay "
                "(check table — may be flat or worse).\n"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
