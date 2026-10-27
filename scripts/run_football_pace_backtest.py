#!/usr/bin/env python3
"""Walk-forward backtest for shadow NFL / NCAAF pace model (free data only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sharp_scout.football_pace.backtest import graded_to_markdown, run_backtest_for_sport
from sharp_scout.utils.odds import setup_logging

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CSV_DIR = DOCS / "data"


def main() -> int:
    parser = argparse.ArgumentParser(description="Football pace model walk-forward backtest")
    parser.add_argument("--sport", choices=("nfl", "ncaaf", "both"), default="both")
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        default=[2023, 2024, 2025, 2026],
        help="Seasons to include (walk-forward, no lookahead)",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    setup_logging(args.log_level)

    sports = ["nfl", "ncaaf"] if args.sport == "both" else [args.sport]
    summaries = {}
    CSV_DIR.mkdir(parents=True, exist_ok=True)

    md_parts = [
        "# Football pace model — walk-forward backtest",
        "",
        "Shadow-only research model (tempo × opponent-adjusted efficiency). "
        "Does not affect live Sharp Scout picks or the public site.",
        "",
        "## Data sources",
        "",
        "- **NFL:** nflverse `games.parquet` (closing spread/total, finals) and play-by-play parquets "
        "(tempo and efficiency; garbage-time filtered via win probability).",
        "- **NCAAF:** sportsdataverse cfbfastR play-by-play parquets (`spread`, `over_under`, scores). "
        "FBS vs FBS games only. Official schedule parquet URLs currently 404; lines come from PBP.",
        "- **CollegeFootballData.com:** optional; requires a free API key (`COLLEGE_FOOTBALL_DATA_API_KEY`) "
        "— not used here because no key is configured in this environment.",
        "",
        "**Injury adjustments:** live via ESPN + nflverse rosters; NFL backtest uses nflverse "
        "weekly injury reports. See `docs/football_pace_injury_adjust.md`. NCAAF has no free "
        "historical injury feed — injury-adjusted backtest columns are empty for college.",
        "",
        "## Default minimum edges",
        "",
        "| Sport | Spread | Total |",
        "|---|---:|---:|",
        "| NFL | 2.5 pts | 2.5 pts |",
        "| NCAAF | 3.5 pts | 3.5 pts |",
        "",
        "Edge buckets in tables: 3–5, 5–7, 7+ points (absolute gap vs closing line).",
        "",
    ]

    for sport in sports:
        df, summary = run_backtest_for_sport(sport, args.seasons)
        csv_path = CSV_DIR / f"football_pace_backtest_{sport}.csv"
        df.to_csv(csv_path, index=False)
        summaries[sport] = summary
        md_parts.append(graded_to_markdown(summary))
        md_parts.append("")

    report_path = DOCS / "football_pace_backtest.md"
    report_path.write_text("\n".join(md_parts) + "\n")
    print(json.dumps(summaries, indent=2))
    print(f"Wrote {report_path} and CSVs under {CSV_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
