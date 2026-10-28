#!/usr/bin/env python3
"""Shadow: 2026-only CFB drive Monte Carlo for current weekly slate (ESPN lines, no Odds API)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sharp_scout.football_pace.cfb_sim.export import run_week_simulation
from sharp_scout.utils.odds import setup_logging

ET = ZoneInfo("America/New_York")


def main() -> int:
    parser = argparse.ArgumentParser(description="CFB drive Monte Carlo weekly slate")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--sims", type=int, default=10_000)
    parser.add_argument(
        "--et-date",
        type=str,
        default=None,
        help="Only games kicking off on this ET calendar date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--tonight",
        action="store_true",
        help="Shortcut for --et-date=<today ET>",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    setup_logging(args.log_level)
    kickoff_et: date | None = None
    if args.tonight:
        kickoff_et = datetime.now(timezone.utc).astimezone(ET).date()
    elif args.et_date:
        kickoff_et = date.fromisoformat(args.et_date)
    out = run_week_simulation(season=args.season, n_sims=args.sims, kickoff_et_date=kickoff_et)
    print(json.dumps({k: out[k] for k in out if k != "games"}, indent=2))
    print(f"Games: {len(out.get('games') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
