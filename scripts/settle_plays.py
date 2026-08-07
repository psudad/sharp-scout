#!/usr/bin/env python3
"""Settle pending ledger plays from nflverse final scores (or manual JSON)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.ledger.tracker import (  # noqa: E402
    compute_record,
    load_scores_from_schedules,
    settle_from_scores,
)
from sharp_scout.site.build import build_site  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Settle Sharp Scout ledger plays")
    p.add_argument("--scores-json", type=Path, help="Optional JSON list of score dicts")
    p.add_argument("--season", type=int, action="append", default=None)
    p.add_argument("--build-site", action="store_true")
    p.add_argument(
        "--manual",
        nargs=4,
        metavar=("AWAY", "HOME", "AWAY_SCORE", "HOME_SCORE"),
        help="Manually settle one game: KC BUF 24 20",
    )
    args = p.parse_args()

    scores = []
    if args.manual:
        away, home, away_s, home_s = args.manual
        scores.append(
            {
                "away_team": away.upper(),
                "home_team": home.upper(),
                "away_score": int(away_s),
                "home_score": int(home_s),
            }
        )
    elif args.scores_json:
        scores = json.loads(args.scores_json.read_text())
    else:
        seasons = args.season or None
        scores = load_scores_from_schedules(seasons)

    ledger = settle_from_scores(scores)
    record = compute_record(ledger)
    if args.build_site:
        build_site()
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
