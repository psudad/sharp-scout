#!/usr/bin/env python3
"""Shadow football pace: tune params, project current week, grade completed (no Odds API)."""

from __future__ import annotations

import argparse
import json
import sys

from sharp_scout.football_pace.export import write_week_artifacts
from sharp_scout.football_pace.tracking import record_and_grade_completed
from sharp_scout.football_pace.week import current_season, nfl_week_from_espn, ncaaf_week_from_espn
from sharp_scout.utils.odds import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow football pace weekly job")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--nfl-week", type=int, default=None)
    parser.add_argument("--ncaaf-week", type=int, default=None)
    parser.add_argument("--grade", action="store_true", help="Grade completed games for season")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    setup_logging(args.log_level)
    season = args.season or current_season()
    nfl_w = args.nfl_week if args.nfl_week is not None else nfl_week_from_espn(season)
    ncaaf_w = args.ncaaf_week if args.ncaaf_week is not None else ncaaf_week_from_espn(season)
    out: dict = {"season": season, "nfl_week": nfl_w, "ncaaf_week": ncaaf_w}
    if args.grade:
        out["graded"] = {
            "nfl": record_and_grade_completed("nfl", season),
            "ncaaf": record_and_grade_completed("ncaaf", season),
        }
    out["artifacts"] = write_week_artifacts(season=season, nfl_week=nfl_w, ncaaf_week=ncaaf_w)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
