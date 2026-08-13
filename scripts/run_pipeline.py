#!/usr/bin/env python3
"""CLI entry: run the Sharp Scout 4-phase pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.pipeline.run import run_pipeline  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Sharp Scout NFL pipeline")
    p.add_argument("--demo", action="store_true", help="Mock odds + splits (no API keys)")
    p.add_argument("--skip-pbp", action="store_true", help="Skip nflverse PBP download")
    p.add_argument("--no-persist", action="store_true", help="Do not write SQLite")
    p.add_argument("--no-ledger", action="store_true", help="Do not append to data/ledger.json")
    p.add_argument("--build-site", action="store_true", help="Regenerate docs/ for GitHub Pages")
    p.add_argument("--season", type=int, default=None)
    p.add_argument("--week", type=int, default=None)
    args = p.parse_args()

    result = run_pipeline(
        demo=args.demo,
        persist=not args.no_persist,
        skip_pbp=args.skip_pbp or args.demo,
        update_ledger=not args.no_ledger,
        build_pages=args.build_site,
        season=args.season,
        week=args.week,
    )
    summary = {
        "generated_at": result["generated_at"],
        "demo": result["demo"],
        "n_games": result["n_games"],
        "n_candidates": result["n_candidates"],
        "n_validated": result["n_validated"],
        "record": result.get("record"),
        "plays": [
            {
                "matchup": f"{s['away_team']}@{s['home_team']}",
                "market": s["market"],
                "side": s["side"],
                "line": s["line"],
                "book": s["book"],
                "price": s["price"],
                "edge": s["edge"],
                "tier": s["tier"],
            }
            for s in result["plays"]
        ],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
