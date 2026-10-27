#!/usr/bin/env python3
"""Project current-week NFL / NCAAF games with the shadow pace model (no Odds API)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from sharp_scout.football_pace.tracking import project_slate, record_and_grade_completed, save_store, load_store
from sharp_scout.utils.odds import setup_logging


def _default_season() -> int:
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 8 else now.year - 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow football pace model — weekly projections")
    parser.add_argument("--sport", choices=("nfl", "ncaaf", "both"), default="both")
    parser.add_argument("--season", type=int, default=_default_season())
    parser.add_argument("--week", type=int, default=None, help="Limit to one week (default: all remaining)")
    parser.add_argument("--save", action="store_true", help="Write data/shadow/football_pace/*.json")
    parser.add_argument("--grade-completed", action="store_true", help="Refresh graded summary for season")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    setup_logging(args.log_level)

    sports = ["nfl", "ncaaf"] if args.sport == "both" else [args.sport]
    payload: dict = {"season": args.season, "week": args.week, "sports": {}}
    for sport in sports:
        if args.grade_completed:
            payload["sports"][sport] = {"summary": record_and_grade_completed(sport, args.season)}
            continue
        rows = project_slate(sport, season=args.season, week=args.week)
        payload["sports"][sport] = {"count": len(rows), "projections": rows}
        if args.save:
            store = load_store(sport)
            store["last_slate"] = rows
            store["season"] = args.season
            save_store(sport, store)

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
