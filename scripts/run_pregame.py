#!/usr/bin/env python3
"""Run pregame windows (T-12h / T-3h / T-1h): sides + player props."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.scheduler.pregame import run_due_pregame  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Sharp Scout pregame scheduler")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--force-all", action="store_true", help="Run all upcoming (ignore windows)")
    p.add_argument("--skip-pbp", action="store_true")
    p.add_argument("--no-site", action="store_true")
    p.add_argument(
        "--ledger",
        action="store_true",
        help="Append validated plays to data/ledger.json (default: off for NFL)",
    )
    args = p.parse_args()
    result = run_due_pregame(
        demo=args.demo,
        force_all_upcoming=args.force_all,
        build_pages=not args.no_site,
        skip_pbp=args.skip_pbp or args.demo,
        update_ledger=args.ledger,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
