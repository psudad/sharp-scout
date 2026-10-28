#!/usr/bin/env python3
"""Walk-forward backtest for shadow NFL / NCAAF pace model (free data only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sharp_scout.config import DATA_DIR
from sharp_scout.football_pace.backtest import (
    comparison_markdown,
    graded_to_markdown,
    legacy_pace_config,
    run_backtest_for_sport,
)
from sharp_scout.football_pace.config import NCAAF_PACE_CONFIG, NFL_PACE_CONFIG
from sharp_scout.utils.odds import setup_logging

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CSV_DIR = DOCS / "data"
TUNING_PATH = DATA_DIR / "shadow" / "football_pace" / "tuning.json"


def _load_tuning() -> dict:
    if not TUNING_PATH.exists():
        return {}
    return json.loads(TUNING_PATH.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description="Football pace model walk-forward backtest")
    parser.add_argument("--sport", choices=("nfl", "ncaaf", "both"), default="both")
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        default=[2023, 2024, 2025, 2026],
        help="Seasons for full CSV export (walk-forward)",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    setup_logging(args.log_level)

    sports = ["nfl", "ncaaf"] if args.sport == "both" else [args.sport]
    summaries = {}
    tuning_doc = _load_tuning()
    CSV_DIR.mkdir(parents=True, exist_ok=True)

    md_parts = [
        "# Football pace model — walk-forward backtest",
        "",
        "Shadow-only research model (tempo × opponent-adjusted efficiency). "
        "Does not affect live Sharp Scout picks or the public site.",
        "",
        "## Data sources",
        "",
        "- **NFL:** nflverse schedules + PBP (closing spread/total, finals).",
        "- **NCAAF:** cfbfastR PBP (`spread`, `over_under`, scores); FBS + FCS where lines exist.",
        "",
        "**Injury adjustments:** NFL backtest uses nflverse weekly reports; NCAAF has no free "
        "historical injury feed. See `docs/football_pace_injury_adjust.md`.",
        "",
        "## Tuning methodology",
        "",
        "Parameters tuned on **2023–2024** only (`scripts/tune_football_pace.py`): market blend toward "
        "close, optional edge caps, and min edges targeting ~10–25% combined play rate. "
        "Holdout **2025–2026** reported separately below.",
        "",
    ]

    train = [2023, 2024]
    holdout = [2025, 2026]

    for sport in sports:
        tuned_cfg = NFL_PACE_CONFIG if sport == "nfl" else NCAAF_PACE_CONFIG
        leg_cfg = legacy_pace_config(sport)
        params = tuning_doc.get(sport)

        legacy_is = run_backtest_for_sport(sport, train, cfg=leg_cfg)[1]
        tuned_is = run_backtest_for_sport(sport, train, cfg=tuned_cfg)[1]
        legacy_oos = run_backtest_for_sport(sport, holdout, cfg=leg_cfg)[1]
        tuned_oos = run_backtest_for_sport(sport, holdout, cfg=tuned_cfg)[1]

        df, summary = run_backtest_for_sport(sport, args.seasons, cfg=tuned_cfg)
        csv_path = CSV_DIR / f"football_pace_backtest_{sport}.csv"
        df.to_csv(csv_path, index=False)
        summaries[sport] = summary

        band = tuning_doc.get("nfl_holdout_injury_spread_band_5_7") if sport == "nfl" else None
        md_parts.append(
            comparison_markdown(
                sport,
                legacy_is=legacy_is,
                tuned_is=tuned_is,
                legacy_oos=legacy_oos,
                tuned_oos=tuned_oos,
                tuning_params=params,
                nfl_injury_band_5_7=band,
            )
        )
        md_parts.append(graded_to_markdown(summary))
        md_parts.append("")

    report_path = DOCS / "football_pace_backtest.md"
    report_path.write_text("\n".join(md_parts) + "\n")
    print(json.dumps(summaries, indent=2))
    print(f"Wrote {report_path} and CSVs under {CSV_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
