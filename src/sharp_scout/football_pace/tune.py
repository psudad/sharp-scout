"""Walk-forward tuning (in-sample seasons) with OOS holdout reporting."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Any

from sharp_scout.football_pace.backtest import GradedRow, _default_plays, _grade_row, summarize_graded
from sharp_scout.football_pace.injury_context import InjuryBacktestContext, build_injury_context
from sharp_scout.football_pace.config import NCAAF_PACE_CONFIG, NFL_PACE_CONFIG, SportPaceConfig
from sharp_scout.football_pace.engine import PaceEngine
from sharp_scout.football_pace.games import PaceGame, load_ncaaf_games, load_nfl_games
from sharp_scout.football_pace.market_blend import BlendParams, blend_projection
from sharp_scout.football_pace.injury_adjust import project_with_injuries


@dataclass
class _CachedGame:
    game: PaceGame
    raw: dict[str, float]
    adj_raw: dict[str, float] | None


def _collect_cached(
    games: list[PaceGame],
    cfg: SportPaceConfig,
    injury_ctx: InjuryBacktestContext | None,
) -> list[_CachedGame]:
    """Single walk-forward pass; blend/thresholds applied later."""
    engine = PaceEngine(cfg)
    out: list[_CachedGame] = []
    last_season = None
    ctx = injury_ctx
    for g in games:
        if last_season is not None and g.season != last_season:
            engine.end_season()
            engine.start_new_season()
        last_season = g.season
        has_scores = g.home_score is not None and g.away_score is not None
        has_lines = g.spread_home is not None and g.total_line is not None
        if has_scores and has_lines:
            raw = engine.project(g.home, g.away)
            adj_raw: dict[str, float] | None = None
            if ctx and ctx.historical_injuries:
                home_inj, away_inj = ctx.injuries_for(g)
                if (home_inj or away_inj) and ctx:
                    adj_raw = project_with_injuries(
                        raw,
                        home_injuries=home_inj,
                        away_injuries=away_inj,
                        tracker=ctx.tracker,
                        home_roster=ctx.roster_names(g.home),
                        away_roster=ctx.roster_names(g.away),
                    )
            out.append(_CachedGame(game=g, raw=raw, adj_raw=adj_raw))
        if has_scores:
            hp = g.home_plays if g.home_plays and g.home_plays > 0 else _default_plays(cfg)
            ap = g.away_plays if g.away_plays and g.away_plays > 0 else _default_plays(cfg)
            engine.observe(
                home=g.home,
                away=g.away,
                home_plays=hp,
                away_plays=ap,
                home_pts=float(g.home_score),
                away_pts=float(g.away_score),
                game_date=g.game_date,
            )
            if ctx:
                touches = ctx.touch_by_game.get(g.game_id, [])
                if touches:
                    ctx.tracker.observe_game_touches(game_id=g.game_id, touches=touches)
    return out


def _rows_from_cache(
    cached: list[_CachedGame],
    cfg: SportPaceConfig,
    blend: BlendParams,
) -> list[GradedRow]:
    cfg_blend = replace(cfg, blend=blend)
    rows: list[GradedRow] = []
    for item in cached:
        g = item.game
        proj = blend_projection(
            item.raw,
            spread_home=g.spread_home,
            total_line=g.total_line,
            params=blend,
        )
        graded = _grade_row(g, proj, cfg_blend)
        adj_fields: dict[str, Any] = {
            k: None
            for k in (
                "proj_margin_adj",
                "proj_total_adj",
                "spread_edge_adj",
                "total_edge_adj",
                "spread_result_adj",
                "total_result_adj",
                "spread_bucket_adj",
                "total_bucket_adj",
            )
        }
        if item.adj_raw is not None:
            adj = blend_projection(
                item.adj_raw,
                spread_home=g.spread_home,
                total_line=g.total_line,
                params=blend,
            )
            graded_adj = _grade_row(g, adj, cfg_blend, suffix="adj")
            adj_fields = {k: graded_adj[k] for k in adj_fields}
        rows.append(
            GradedRow(
                sport=g.sport,
                season=g.season,
                week=g.week,
                game_id=g.game_id,
                home=g.home,
                away=g.away,
                spread_home=g.spread_home,
                total_line=g.total_line,
                actual_margin=float(g.home_score) - float(g.away_score),
                actual_total=float(g.home_score) + float(g.away_score),
                proj_margin=graded["proj_margin"],
                proj_total=graded["proj_total"],
                spread_edge=graded["spread_edge"],
                total_edge=graded["total_edge"],
                spread_result=graded["spread_result"],
                total_result=graded["total_result"],
                spread_bucket=graded["spread_bucket"],
                total_bucket=graded["total_bucket"],
                **adj_fields,
            )
        )
    return rows


def _play_rate(summary: dict[str, Any]) -> float:
    n = summary.get("games_with_lines") or 0
    if n == 0:
        return 0.0
    sp = summary.get("spread") or {}
    tot = summary.get("total") or {}
    return ((sp.get("picks") or 0) + (tot.get("picks") or 0)) / (2.0 * n) * 100.0


def _score(summary: dict[str, Any]) -> float:
    sp = summary.get("spread") or {}
    roi = sp.get("roi_pct_at_110")
    if roi is None:
        roi = 0.0
    rate = _play_rate(summary)
    penalty = 0.0
    if rate < 10.0:
        penalty = (10.0 - rate) * 0.5
    elif rate > 25.0:
        penalty = (rate - 25.0) * 0.5
    return float(roi) - penalty


def _load_games(sport: str, seasons: list[int]) -> tuple[list[PaceGame], SportPaceConfig, InjuryBacktestContext]:
    if sport == "nfl":
        base = NFL_PACE_CONFIG
        games = load_nfl_games(seasons)
    else:
        base = NCAAF_PACE_CONFIG
        games = load_ncaaf_games(seasons, fbs_only=False)
        games = [g for g in games if g.spread_home is not None and g.total_line is not None]
    ctx = build_injury_context(sport, seasons)
    return games, base, ctx


def tune_sport(sport: str, train_seasons: list[int]) -> dict[str, Any]:
    games, base, ctx = _load_games(sport, train_seasons)
    cached = _collect_cached(games, base, ctx)

    if sport == "nfl":
        grid_blend = (0.35, 0.45, 0.55)
        grid_edge_sp = (5.0, 6.0, 7.0, 8.0)
        grid_edge_tot = (5.0, 6.0, 7.0, 8.0)
        grid_cap = (None, 6.0, 8.0)
    else:
        grid_blend = (0.45, 0.55, 0.65, 0.75)
        grid_edge_sp = (8.0, 9.0, 10.0, 11.0, 12.0)
        grid_edge_tot = (8.0, 9.0, 10.0, 11.0, 12.0)
        grid_cap = (None, 6.0)

    best: dict[str, Any] | None = None
    best_score = -999.0
    for bm, bt, cap, es, et in itertools.product(grid_blend, grid_blend, grid_cap, grid_edge_sp, grid_edge_tot):
        if cap is not None and (es > cap or et > cap):
            continue
        blend = BlendParams(bm, bt, max_edge_spread=cap, max_edge_total=cap)
        cfg = replace(base, min_edge_spread=es, min_edge_total=et)
        rows = _rows_from_cache(cached, cfg, blend)
        grade_variant = "adj" if sport == "nfl" else "raw"
        summ = summarize_graded(rows, cfg, variant=grade_variant)
        sc = _score(summ)
        rate = _play_rate(summ)
        if 8.0 <= rate <= 28.0 and sc > best_score:
            best_score = sc
            best = {
                "market_blend_margin": bm,
                "market_blend_total": bt,
                "max_edge_spread": cap,
                "max_edge_total": cap,
                "min_edge_spread": es,
                "min_edge_total": et,
                "in_sample_spread_roi": summ["spread"].get("roi_pct_at_110"),
                "in_sample_play_rate_pct": round(rate, 2),
                "score": round(sc, 3),
            }
    if best is None:
        best = {
            "market_blend_margin": 0.55,
            "market_blend_total": 0.55,
            "max_edge_spread": 6.0,
            "max_edge_total": 6.0,
            "min_edge_spread": 7.0,
            "min_edge_total": 7.0,
            "in_sample_spread_roi": None,
            "in_sample_play_rate_pct": None,
            "score": None,
        }
    return best


def evaluate_holdout(
    sport: str,
    seasons: list[int],
    params: dict[str, Any],
) -> dict[str, Any]:
    blend = BlendParams(
        float(params["market_blend_margin"]),
        float(params["market_blend_total"]),
        max_edge_spread=params.get("max_edge_spread"),
        max_edge_total=params.get("max_edge_total"),
    )
    games, base, ctx = _load_games(sport, seasons)
    cached = _collect_cached(games, base, ctx)
    cfg = replace(
        base,
        min_edge_spread=float(params["min_edge_spread"]),
        min_edge_total=float(params["min_edge_total"]),
        lean_min_edge_spread=float(params.get("lean_min_edge_spread") or params["min_edge_spread"]) - 2.0,
        lean_min_edge_total=float(params.get("lean_min_edge_total") or params["min_edge_total"]) - 2.0,
    )
    rows = _rows_from_cache(cached, cfg, blend)
    return {
        "unadjusted": summarize_graded(rows, cfg, variant="raw"),
        "injury_adjusted": summarize_graded(rows, cfg, variant="adj"),
        "params": params,
        "seasons": seasons,
    }
