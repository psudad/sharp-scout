#!/usr/bin/env python3
"""Tune market blend + min edges on 2023-2024; write data/shadow/football_pace/tuning.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sharp_scout.config import DATA_DIR
from sharp_scout.football_pace.tune import evaluate_holdout, tune_sport
from sharp_scout.utils.odds import setup_logging


def main() -> int:
    setup_logging("INFO")
    out_dir = DATA_DIR / "shadow" / "football_pace"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {"train_seasons": [2023, 2024], "holdout_seasons": [2025, 2026]}
    for sport in ("nfl", "ncaaf"):
        best = tune_sport(sport, [2023, 2024])
        best["lean_min_edge_spread"] = float(best["min_edge_spread"]) - 2.0
        best["lean_min_edge_total"] = float(best["min_edge_total"]) - 2.0
        payload[sport] = best
        hold = evaluate_holdout(sport, [2025, 2026], best)
        payload[f"{sport}_holdout"] = hold
        if sport == "nfl":
            from dataclasses import replace

            from sharp_scout.football_pace.config import NFL_PACE_CONFIG
            from sharp_scout.football_pace.tune import _collect_cached, _load_games, _rows_from_cache
            from sharp_scout.football_pace.market_blend import BlendParams

            band_params = {**best, "min_edge_spread": 5.0}
            blend = BlendParams(
                float(best["market_blend_margin"]),
                float(best["market_blend_total"]),
                max_edge_spread=best.get("max_edge_spread"),
                max_edge_total=best.get("max_edge_total"),
            )
            games, base, ctx = _load_games("nfl", [2025, 2026])
            cached = _collect_cached(games, base, ctx)
            cfg = replace(NFL_PACE_CONFIG, min_edge_spread=5.0, min_edge_total=float(best["min_edge_total"]))
            rows = _rows_from_cache(cached, cfg, blend)
            from sharp_scout.football_pace.backtest import summarize_graded

            adj = summarize_graded(rows, cfg, variant="adj")
            bucket = (adj.get("spread_by_edge_bucket") or {}).get("5-7")
            payload["nfl_holdout_injury_spread_band_5_7"] = bucket
    path = out_dir / "tuning.json"
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
