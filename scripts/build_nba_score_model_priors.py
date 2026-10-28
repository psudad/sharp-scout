#!/usr/bin/env python3
"""Offline: replay ESPN finals into stage-3 engine → regressed priors JSON (commit output)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR
from sharp_scout.data.espn_nba import fetch_espn_nba_finals_by_event
from sharp_scout.nba.rosters import ESPN_NBA_SEASON_END_YEAR
from sharp_scout.nba.score_model.engine import V2Engine, V2Params, TeamPrior
from sharp_scout.nba.score_model.roster_priors import ROSTER_PRIOR_WEIGHT, build_roster_weighted_priors
from sharp_scout.nba.score_model.state import _games_from_scores, _replay_games, _season_label

DEFAULT_OUT = DATA_DIR / "paper" / "nba_score_model_priors.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season-start", default="2025-10-01", help="ISO date (inclusive)")
    parser.add_argument("--season-end", default="2026-06-30", help="ISO date (inclusive)")
    parser.add_argument("--for-season", default="2026-27", help="Label for priors target season")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    since = datetime.fromisoformat(args.season_start).replace(tzinfo=timezone.utc)
    until = datetime.fromisoformat(args.season_end).replace(tzinfo=timezone.utc)
    scores = fetch_espn_nba_finals_by_event(since=since, until=until)
    poss_cache: dict[str, float] = {}
    games = _games_from_scores(scores, poss_cache=poss_cache)
    engine = V2Engine(params=V2Params(), stage=3)
    processed: set[str] = set()
    _replay_games(engine, games, processed)  # noqa: SLF001
    engine.end_season()
    reg = engine.params.prior_regress_frac
    blended = build_roster_weighted_priors(
        regressed_team_priors=engine.end_season_priors,
        season_end_year=ESPN_NBA_SEASON_END_YEAR,
    )
    teams = {
        t: {
            "off": round(p.off, 3),
            "def": round(p.def_, 3),
            "pace": round(p.pace, 3),
        }
        for t, p in blended.items()
    }
    payload = {
        "version": 2,
        "for_season": args.for_season,
        "built_from": f"ESPN finals {args.season_start}..{args.season_end}",
        "prior_method": (
            f"{ROSTER_PRIOR_WEIGHT:.0%} live ESPN roster minutes-weighted player BPM proxy + "
            f"{1 - ROSTER_PRIOR_WEIGHT:.0%} regressed prior-season team ratings (no Odds API)"
        ),
        "regress_frac": reg,
        "n_games": len(processed),
        "teams": teams,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {args.out} ({len(teams)} teams, {len(processed)} games)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
