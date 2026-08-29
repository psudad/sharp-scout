#!/usr/bin/env python3
"""On-demand board refresh: settle → live market scan → rebuild GitHub Pages site.

Use this whenever you want current value lines posted without waiting for cron.

Examples:
  python scripts/refresh_board.py
  python scripts/refresh_board.py --ncaaf-only
  python scripts/refresh_board.py --demo --skip-pbp
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(argv: list[str]) -> None:
    cmd = [sys.executable, *argv]
    print(">>>", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Refresh Sharp Scout from the live market and rebuild docs/"
    )
    p.add_argument("--demo", action="store_true", help="Mock odds + splits (no API keys)")
    p.add_argument("--skip-pbp", action="store_true", help="Skip nflverse / cfbfastR download")
    p.add_argument("--ncaaf-only", action="store_true", help="Skip NFL signals refresh")
    p.add_argument("--nfl-only", action="store_true", help="Skip NCAAF ledger refresh")
    p.add_argument("--no-settle", action="store_true", help="Skip grading completed games")
    p.add_argument("--no-site", action="store_true", help="Skip docs/ rebuild")
    p.add_argument(
        "--all-games",
        action="store_true",
        help="NCAAF: include all posted games (default: current college week only)",
    )
    args = p.parse_args()

    if args.ncaaf_only and args.nfl_only:
        p.error("Use at most one of --ncaaf-only / --nfl-only")

    if not args.no_settle:
        if not args.nfl_only:
            _run(["scripts/settle_plays.py", "--sport", "ncaaf"])
        if not args.ncaaf_only:
            _run(["scripts/settle_plays.py"])

    nfl_args = ["scripts/run_pipeline.py"]
    ncaaf_args = ["scripts/run_ncaaf.py"]
    if args.demo:
        nfl_args.append("--demo")
        ncaaf_args.append("--demo")
    if args.skip_pbp or args.demo:
        nfl_args.append("--skip-pbp")
        ncaaf_args.append("--skip-pbp")
    if args.all_games:
        ncaaf_args.append("--all-games")

    if not args.ncaaf_only:
        _run(nfl_args)
    if not args.nfl_only:
        _run(ncaaf_args)

    if not args.no_site:
        _run(["scripts/build_site.py"])


if __name__ == "__main__":
    main()
