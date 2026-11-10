#!/usr/bin/env python3
"""Backtest v1 Pace market anchoring weights (research only)."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from nba_pace_projection_backtest_lib import (  # noqa: E402
    ESPN_LINES_PATH,
    run_projection_backtest,
    season_bounds,
)
from sharp_scout.config import DATA_DIR  # noqa: E402


def _run_weight(model_weight: float, **kwargs) -> dict:
    os.environ["NBA_PACE_V1_MARKET_BLEND_ENABLED"] = "false" if model_weight >= 0.999 else "true"
    os.environ["NBA_PACE_V1_MARKET_BLEND_MODEL_WEIGHT"] = str(model_weight)
    from sharp_scout.config import get_settings

    get_settings.cache_clear()
    try:
        return run_projection_backtest(label=f"w={model_weight}", **kwargs)
    finally:
        get_settings.cache_clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper", type=Path, default=DATA_DIR / "paper" / "nba_score_model.json")
    parser.add_argument("--espn-lines", type=Path, default=ESPN_LINES_PATH)
    parser.add_argument("--through", default=None, help="ET through date (default today)")
    args = parser.parse_args()
    through = date.fromisoformat(args.through) if args.through else date.today()
    start, _ = season_bounds("2026-27")
    kw = dict(season_start=start, through=through, paper_path=args.paper, espn_lines_path=args.espn_lines)

    print(
        "## Lines\n"
        "Repo pre-tip scans + ESPN pickcenter backfill; ESPN finals; walk-forward engine.\n"
        f"Season 2026-27 through **{through}** ET.\n"
    )
    print("| Model weight | Games | Mean bias | MAE actual | MAE close | Totals W-L-P | Units | O / U |")
    print("|---|--:|---:|---:|---:|---|--:|---|")
    for w in (1.0, 0.5, 0.35, 0.3):
        r = _run_weight(w, **kw)
        ag = r["all_games_projection"]
        tp = r["totals_picks"]
        print(
            f"| {w:.2f} | {ag.get('n', 0)} | {ag.get('mean_bias', '—')} | {ag.get('mae_vs_actual', '—')} | "
            f"{ag.get('mae_vs_close', '—')} | {tp['record']} ({tp['n']}) | {tp['units_1u_110']:+.2f} | "
            f"{tp['overs']} / {tp['unders']} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
