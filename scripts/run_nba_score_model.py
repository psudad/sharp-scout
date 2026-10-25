#!/usr/bin/env python3
"""Research: walk-forward NBA score projection vs closing lines (no Odds API)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sharp_scout.research.nba_score_model.data_loader import load_all_games
from sharp_scout.research.nba_score_model.evaluate import (
    project_tonight_slate,
    render_markdown,
    summarize,
    tune_blend,
    tune_params,
    walk_forward,
    write_csv,
)
from sharp_scout.research.nba_score_model.ratings import RatingEngine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SBR = ROOT / "research/cache/nba_archive_10Y.json"
ESPN_CACHE = ROOT / "research/cache/espn_nba_score_index.json"
SHADOW_HIST = ROOT / "data/shadow/nba_line_history.json"


def main() -> None:
    ap = argparse.ArgumentParser(description="NBA score projection research backtest")
    ap.add_argument("--sbr-path", type=Path, default=DEFAULT_SBR)
    ap.add_argument("--refresh-espn", action="store_true", help="Rebuild ESPN score cache (~2200 API days)")
    ap.add_argument("--report-stamp", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    args = ap.parse_args()

    games, data_meta = load_all_games(args.sbr_path, espn_cache=ESPN_CACHE, refresh_espn=args.refresh_espn)
    if len(games) < 500:
        raise SystemExit(f"Too few graded games ({len(games)}); check SBR path and ESPN cache.")
    print("Yahoo joined", data_meta["yahoo_joined"], "/", data_meta["yahoo_rows"], "rejected", data_meta["yahoo_rejected_no_match"])
    print("OOS line QA", data_meta.get("line_diagnostics_oos"))

    params = tune_params(games)
    ev = walk_forward(games, params)
    blend_w = tune_blend(ev.preds)

    # Re-run walk-forward for slate engine at end of full sample
    engine = RatingEngine(params=params)
    last_season = None
    last_played: dict[str, datetime] = {}
    from sharp_scout.research.nba_score_model.evaluate import _rest_days

    for g in games:
        season = g["season"]
        if last_season and season != last_season:
            engine.snapshot_season_end()
            engine.new_season()
        last_season = season
        dt = g["date"]
        hr = _rest_days(g["home"], dt, last_played)
        ar = _rest_days(g["away"], dt, last_played)
        engine.project(g["home"], g["away"], game_date=dt, home_rest=hr, away_rest=ar)
        engine.observe(g)
        last_played[g["home"]] = dt
        last_played[g["away"]] = dt

    summary = summarize(ev.preds, blend_w)
    summary["data_quality"] = data_meta
    summary["bugs_fixed_in_this_run"] = [
        "Yahoo↔ESPN score join used undated away@home fallback (latest rematch), pairing wrong finals to closing lines.",
        "ESPN cache keyed by kickoff date with sparse coverage; rebuilt as scoreboard-request-date keys only (v2).",
        "Yahoo scores now require spread_home_won / total_over_won agreement (±1 day date shift allowed).",
    ]
    summary["params"] = {
        "recency_half_life_days": params.recency_half_life_days,
        "hca_points": params.hca_points,
        "b2b_penalty": params.b2b_penalty,
        "shrink_games": params.shrink_games,
        "prior_carry": params.prior_carry,
    }
    summary["n_all_games"] = len(games)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()

    slate = project_tonight_slate(engine, shadow_history=SHADOW_HIST, last_played=last_played)
    summary["tonight_slate"] = slate

    report_dir = ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    stem = f"nba_score_model_{args.report_stamp}"
    csv_path = report_dir / f"{stem}.csv"
    md_path = report_dir / f"{stem}.md"
    json_path = report_dir / f"{stem}.json"

    oos_preds = [p for p in ev.preds if p.season in summary.get("oos_seasons", ())]
    write_csv(csv_path, oos_preds)
    md_path.write_text(render_markdown(summary, slate))
    json_path.write_text(json.dumps(summary, indent=2))

    print(f"Games: {len(games)} | OOS: {summary['n_oos_games']}")
    print(f"Margin MAE model={summary['margin_mae']['model']} market={summary['margin_mae']['market']}")
    print(f"Total MAE model={summary['total_mae']['model']} market={summary['total_mae']['market']}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
