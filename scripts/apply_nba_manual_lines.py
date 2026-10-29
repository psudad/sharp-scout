#!/usr/bin/env python3
"""Apply data/shadow/nba_manual_lines.json and rebuild docs/nba.html (no Odds API)."""

from __future__ import annotations

import argparse
import sys

from sharp_scout.nba.manual_lines import apply_manual_lines_to_paper_store, load_manual_lines
from sharp_scout.nba.score_model.paper import refresh_espn_slate_injury_scans
from sharp_scout.nba.score_model.state import ensure_score_engine
from sharp_scout.site.nba_page import build_nba_page
from sharp_scout.utils.odds import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="NBA manual FanDuel lines → paper store + nba.html")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--skip-injury-refresh", action="store_true")
    parser.add_argument("--no-page", action="store_true")
    args = parser.parse_args()
    setup_logging(args.log_level)

    if not load_manual_lines():
        print("No manual lines file or empty games list.", file=sys.stderr)
        return 1

    n_inj = 0
    if not args.skip_injury_refresh:
        engine = ensure_score_engine()
        n_inj = refresh_espn_slate_injury_scans(engine=engine)
    n_lines = apply_manual_lines_to_paper_store()
    if not args.no_page:
        build_nba_page()
    print(f"injury_rescans={n_inj} manual_line_games={n_lines}")
    return 0 if n_lines else 1


if __name__ == "__main__":
    sys.exit(main())
