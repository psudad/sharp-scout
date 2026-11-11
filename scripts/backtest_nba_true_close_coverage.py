#!/usr/bin/env python3
"""Report how often true-close lines are available in paper scans (research)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba.score_model.paper import load_paper_store
from sharp_scout.nba.score_model.true_close import true_close_lines_for_game


def main() -> int:
    store = load_paper_store()
    graded = [g for g in store.get("games") or [] if g.get("graded")]
    n = len(graded)
    have = sum(1 for g in graded if true_close_lines_for_game(g))
    print(f"Graded paper games: {n}")
    print(f"With true-close scan in (T-15,T+5]: {have} ({100*have/max(n,1):.1f}%)")
    print(
        "Odds API credits when nba_pace_pre_tip_snapshot_enabled=true: "
        "~9 credits per extra game-lines scan; typically 1–3 cap-exempt pre-tip scans/slate "
        "(per-game T-15..T+5 windows; see schedule_guard CRON_CATCHUP), not per game."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
