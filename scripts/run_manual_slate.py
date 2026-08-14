#!/usr/bin/env python3
"""Run pipeline on a manually pasted odds slate (preseason) + live Action Network splits."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.data.manual_odds import load_manual_slate  # noqa: E402
from sharp_scout.pipeline.run import run_pipeline  # noqa: E402
from sharp_scout.utils.odds import setup_logging  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(
        description="Sharp Scout manual slate — pasted odds + Action Network splits"
    )
    p.add_argument("slate", type=Path, help="JSON file with games[] (see data/manual_slate.example.json)")
    p.add_argument(
        "--date",
        default=None,
        help="Action Network slate date YYYYMMDD (default: today UTC or an_date in JSON)",
    )
    p.add_argument("--skip-pbp", action="store_true", help="Skip nflverse download")
    p.add_argument("--no-ledger", action="store_true")
    p.add_argument("--build-site", action="store_true")
    p.add_argument("--season", type=int, default=None)
    p.add_argument("--week", type=int, default=None)
    args = p.parse_args()
    setup_logging("INFO")

    events, an_date = load_manual_slate(args.slate)
    splits_date = args.date or an_date or datetime.utcnow().strftime("%Y%m%d")

    result = run_pipeline(
        demo=False,
        persist=True,
        skip_pbp=args.skip_pbp,
        update_ledger=not args.no_ledger,
        build_pages=args.build_site,
        season=args.season,
        week=args.week,
        events=events,
        splits_date=splits_date,
        fetch_splits=True,
    )
    summary = {
        "generated_at": result["generated_at"],
        "manual_slate": True,
        "splits_date": splits_date,
        "n_games": result["n_games"],
        "n_splits_games": result.get("n_splits_games"),
        "n_candidates": result["n_candidates"],
        "n_validated": result["n_validated"],
        "split_boards_available": sum(1 for b in result.get("split_boards", []) if b.get("available")),
        "plays": result["plays"][:5],
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
