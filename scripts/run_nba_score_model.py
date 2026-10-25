#!/usr/bin/env python3
"""Research: walk-forward NBA score projection vs closing lines (no Odds API)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sharp_scout.research.nba_score_model.box_scores import attach_box_stats_to_games, ensure_box_scores
from sharp_scout.research.nba_score_model.data_loader import load_all_games
from sharp_scout.research.nba_score_model.evaluate import project_tonight_slate
from sharp_scout.research.nba_score_model.ratings import RatingEngine
from sharp_scout.research.nba_score_model.staged_eval import (
    market_move_analysis,
    render_v2_markdown,
    run_all_stages,
    summarize_stage,
    tune_v2_params,
    walk_forward_v2,
)
from sharp_scout.research.nba_score_model.v2_engine import V2Engine, V2Params

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SBR = ROOT / "research/cache/nba_archive_10Y.json"
ESPN_CACHE = ROOT / "research/cache/espn_nba_score_index.json"
BOX_CACHE = ROOT / "research/cache/espn_nba_box_scores.json"
SHADOW_HIST = ROOT / "data/shadow/nba_line_history.json"


def _rebuild_final_engine(games: list[dict], params: V2Params) -> tuple[V2Engine, dict]:
    from sharp_scout.research.nba_score_model.staged_eval import _ensure_poss_fields, _game_context

    engine = V2Engine(params=params, stage=4)
    last_played: dict[str, datetime] = {}
    team_last_site: dict[str, str] = {}
    team_game_dates: dict[str, list[datetime]] = {}
    current_season = None
    for g in games:
        season = g["season"]
        if current_season and season != current_season:
            engine.end_season()
            engine.start_new_season()
        current_season = season
        _ensure_poss_fields(g)
        ctx = _game_context(
            g, last_played=last_played, team_last_site=team_last_site, team_game_dates=team_game_dates
        )
        dt = g["date"]
        engine.project(
            g["home"],
            g["away"],
            game_date=dt,
            home_rest=ctx["home_rest"],
            away_rest=ctx["away_rest"],
            home_3in4=ctx["home_3in4"],
            away_3in4=ctx["away_3in4"],
            home_travel_mi=ctx["home_travel_mi"],
            away_travel_mi=ctx["away_travel_mi"],
            home_player_mins=g.get("home_player_mins"),
            away_player_mins=g.get("away_player_mins"),
        )
        engine.observe(g, ctx=ctx)
        last_played[g["home"]] = dt
        last_played[g["away"]] = dt
        team_last_site[g["home"]] = g["home"]
        team_last_site[g["away"]] = g["away"]
        team_game_dates.setdefault(g["home"], []).append(dt)
        team_game_dates.setdefault(g["away"], []).append(dt)
    return engine, last_played


def main() -> None:
    ap = argparse.ArgumentParser(description="NBA score projection research backtest")
    ap.add_argument("--sbr-path", type=Path, default=DEFAULT_SBR)
    ap.add_argument("--refresh-espn", action="store_true", help="Rebuild ESPN score cache (~2200 API days)")
    ap.add_argument("--fetch-boxes", action="store_true", help="Fetch missing ESPN box scores (slow first run)")
    ap.add_argument("--box-limit", type=int, default=0, help="Max new box scores to fetch (0=all missing)")
    ap.add_argument("--report-stamp", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    args = ap.parse_args()

    games, data_meta = load_all_games(args.sbr_path, espn_cache=ESPN_CACHE, refresh_espn=args.refresh_espn)
    if len(games) < 500:
        raise SystemExit(f"Too few graded games ({len(games)}); check SBR path and ESPN cache.")

    event_ids = sorted({str(g["event_id"]) for g in games if g.get("event_id")})
    if args.fetch_boxes or not BOX_CACHE.exists():
        ensure_box_scores(
            event_ids,
            BOX_CACHE,
            max_fetch=args.box_limit if args.box_limit > 0 else None,
        )
    box_events = json.loads(BOX_CACHE.read_text()).get("events", {}) if BOX_CACHE.exists() else {}
    attach_box_stats_to_games(games, box_events)

    print("Yahoo joined", data_meta["yahoo_joined"], "/", data_meta["yahoo_rows"])
    print("Games with ESPN box poss", sum(1 for g in games if g.get("game_poss")))

    v2_params = tune_v2_params(games, stage=3)
    stage_results = run_all_stages(games, v2_params)
    stage_summaries = [summarize_stage(sr) for sr in stage_results]
    market = market_move_analysis(stage_results[-1].preds)

    engine, last_played = _rebuild_final_engine(games, v2_params)
    # Tonight uses v2 stage-4 via RatingEngine adapter — project_tonight expects v1; use simple v2 project on scoreboard
    slate = _tonight_v2(engine, last_played)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_all_games": len(games),
        "v2_params": v2_params.__dict__,
        "data_quality": data_meta,
        "stages": stage_summaries,
        "market_move_analysis": market,
        "tonight_slate": slate,
    }

    report_dir = ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    stem = f"nba_score_model_{args.report_stamp}"
    md_path = report_dir / f"{stem}.md"
    json_path = report_dir / f"{stem}.json"
    md_path.write_text(render_v2_markdown(stage_summaries, market, slate))
    json_path.write_text(json.dumps(summary, indent=2))

    final = stage_summaries[-1]
    print("Stage ladder (margin MAE model / close):", [(s["stage"], s["mae"]["margin"]["model"], s["mae"]["margin"]["market"]) for s in stage_summaries])
    print("Final OOS margin MAE", final["mae"]["margin"])
    print("Wrote", md_path)


def _tonight_v2(engine: V2Engine, last_played: dict) -> list[dict]:
    from urllib.parse import urlencode

    from sharp_scout.data.espn_cfb import _get_json
    from sharp_scout.research.nba_score_model.data_loader import load_board_lines_from_shadow
    from sharp_scout.research.nba_score_model.evaluate import _rest_days
    from sharp_scout.research.nba_score_model.box_scores import _team_code

    today = datetime.now(timezone.utc)
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?{urlencode({'dates': today.strftime('%Y%m%d'), 'limit': 50})}"
    payload = _get_json(url)
    board = load_board_lines_from_shadow(SHADOW_HIST)
    out = []
    for ev in payload.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        status = ((comp.get("status") or {}).get("type") or {}).get("name") or ""
        if status in ("STATUS_FINAL", "STATUS_FINAL_OVERTIME"):
            continue
        teams = {}
        for c in comp.get("competitors") or []:
            teams[c.get("homeAway")] = _team_code(c.get("team") or {})
        away, home = teams.get("away"), teams.get("home")
        if not away or not home:
            continue
        hr, ar = _rest_days(home, today, last_played), _rest_days(away, today, last_played)
        proj = engine.project(home, away, game_date=today, home_rest=hr, away_rest=ar)
        eid = str(ev.get("id"))
        lines = board.get(eid, {})
        out.append(
            {
                "away": away,
                "home": home,
                "proj_score": f"{proj['away_pts']:.1f}-{proj['home_pts']:.1f}",
                "proj_margin": proj["margin"],
                "proj_total": proj["total"],
                "close_spread": lines.get("spread_home"),
                "close_total": lines.get("total"),
            }
        )
    return out


if __name__ == "__main__":
    main()
