"""Walk-forward backtest and summary tables for shadow football pace model."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from sharp_scout.data.nfl_injuries import injuries_for_team_week, load_nfl_injuries
from sharp_scout.football_pace.config import NCAAF_PACE_CONFIG, NFL_PACE_CONFIG, SportPaceConfig
from sharp_scout.football_pace.engine import PaceEngine
from sharp_scout.football_pace.games import PaceGame, load_ncaaf_games, load_nfl_games
from sharp_scout.football_pace.injury_adjust import project_with_injuries
from sharp_scout.football_pace.lines import edge_bucket_label, grade_ats, grade_total, roi_at_110
from sharp_scout.football_pace.player_value import (
    PlayerValueTracker,
    attach_nflverse_positions,
    build_nfl_game_touch_index,
    build_ncaaf_game_touch_index,
)
from sharp_scout.data.nflfastr import load_pbp
from sharp_scout.data.cfbfastr import load_cfb_pbp


@dataclass
class GradedRow:
    sport: str
    season: int
    week: int
    game_id: str
    home: str
    away: str
    proj_margin: float
    proj_total: float
    proj_margin_adj: float | None
    proj_total_adj: float | None
    spread_home: float | None
    total_line: float | None
    actual_margin: float
    actual_total: float
    spread_edge: float | None
    total_edge: float | None
    spread_edge_adj: float | None
    total_edge_adj: float | None
    spread_result: str | None
    total_result: str | None
    spread_result_adj: str | None
    total_result_adj: str | None
    spread_bucket: str | None
    total_bucket: str | None
    spread_bucket_adj: str | None
    total_bucket_adj: str | None


@dataclass
class InjuryBacktestContext:
    sport: str
    tracker: PlayerValueTracker = field(default_factory=lambda: PlayerValueTracker("nfl"))
    touch_by_game: dict[str, list[tuple[str, str, float]]] = field(default_factory=dict)
    injuries_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    historical_injuries: bool = False

    def injuries_for(self, g: PaceGame) -> tuple[list[dict], list[dict]]:
        if not self.historical_injuries or self.injuries_df.empty:
            return [], []
        home = injuries_for_team_week(self.injuries_df, season=g.season, week=g.week, team=g.home)
        away = injuries_for_team_week(self.injuries_df, season=g.season, week=g.week, team=g.away)
        for row in home + away:
            self.tracker.set_position(row["team"], row["player"], row.get("position") or "")
        return home, away

    def roster_names(self, team: str) -> list[str]:
        team = team.upper()
        names: list[str] = []
        for (t, _key), _ in self.tracker.player_touches.items():
            if t == team:
                names.append(_key)
        for (t, _key) in self.tracker.roster_positions:
            if t == team:
                names.append(_key)
        return names


def build_injury_context(sport: str, seasons: list[int]) -> InjuryBacktestContext:
    ctx = InjuryBacktestContext(sport=sport, tracker=PlayerValueTracker(sport))
    if sport == "nfl":
        pbp = load_pbp(seasons)
        ctx.touch_by_game = build_nfl_game_touch_index(pbp)
        ctx.injuries_df = load_nfl_injuries(seasons)
        ctx.historical_injuries = not ctx.injuries_df.empty
        attach_nflverse_positions(ctx.tracker)
    elif sport == "ncaaf":
        pbp = load_cfb_pbp(seasons)
        ctx.touch_by_game = build_ncaaf_game_touch_index(pbp)
        ctx.historical_injuries = False
    return ctx


def _default_plays(cfg: SportPaceConfig) -> float:
    return cfg.league_plays_per_game


def _grade_row(
    g: PaceGame,
    proj: dict[str, float],
    cfg: SportPaceConfig,
    *,
    suffix: str = "",
) -> dict[str, Any]:
    act_m = float(g.home_score) - float(g.away_score)
    act_t = float(g.home_score) + float(g.away_score)
    spread_edge = proj["margin"] + float(g.spread_home)
    total_edge = proj["total"] - float(g.total_line)
    spread_res = grade_ats(
        act_m,
        float(g.spread_home),
        proj_margin=proj["margin"],
        min_edge=cfg.min_edge_spread,
    )
    total_res = grade_total(
        act_t,
        float(g.total_line),
        proj_total=proj["total"],
        min_edge=cfg.min_edge_total,
    )
    prefix = "" if not suffix else f"_{suffix}"
    return {
        f"proj_margin{prefix}": round(proj["margin"], 3),
        f"proj_total{prefix}": round(proj["total"], 3),
        f"spread_edge{prefix}": round(spread_edge, 3),
        f"total_edge{prefix}": round(total_edge, 3),
        f"spread_result{prefix}": spread_res,
        f"total_result{prefix}": total_res,
        f"spread_bucket{prefix}": edge_bucket_label(abs(spread_edge), cfg.edge_buckets)
        if spread_res
        else None,
        f"total_bucket{prefix}": edge_bucket_label(abs(total_edge), cfg.edge_buckets)
        if total_res
        else None,
    }


def walk_forward_backtest(
    games: list[PaceGame],
    cfg: SportPaceConfig,
    *,
    injury_ctx: InjuryBacktestContext | None = None,
) -> tuple[list[GradedRow], PaceEngine]:
    engine = PaceEngine(cfg)
    rows: list[GradedRow] = []
    last_season: int | None = None
    ctx = injury_ctx

    for g in games:
        if last_season is not None and g.season != last_season:
            engine.end_season()
            engine.start_new_season()
        last_season = g.season

        has_scores = g.home_score is not None and g.away_score is not None
        has_lines = g.spread_home is not None and g.total_line is not None
        if has_scores and has_lines:
            proj = engine.project(g.home, g.away)
            adj_fields: dict[str, Any] = {
                "proj_margin_adj": None,
                "proj_total_adj": None,
                "spread_edge_adj": None,
                "total_edge_adj": None,
                "spread_result_adj": None,
                "total_result_adj": None,
                "spread_bucket_adj": None,
                "total_bucket_adj": None,
            }
            if ctx and ctx.historical_injuries:
                home_inj, away_inj = ctx.injuries_for(g)
                if home_inj or away_inj:
                    adj = project_with_injuries(
                        proj,
                        home_injuries=home_inj,
                        away_injuries=away_inj,
                        tracker=ctx.tracker,
                        home_roster=ctx.roster_names(g.home),
                        away_roster=ctx.roster_names(g.away),
                    )
                    graded_adj = _grade_row(g, adj, cfg, suffix="adj")
                    adj_fields = {
                        "proj_margin_adj": graded_adj["proj_margin_adj"],
                        "proj_total_adj": graded_adj["proj_total_adj"],
                        "spread_edge_adj": graded_adj["spread_edge_adj"],
                        "total_edge_adj": graded_adj["total_edge_adj"],
                        "spread_result_adj": graded_adj["spread_result_adj"],
                        "total_result_adj": graded_adj["total_result_adj"],
                        "spread_bucket_adj": graded_adj["spread_bucket_adj"],
                        "total_bucket_adj": graded_adj["total_bucket_adj"],
                    }
            graded = _grade_row(g, proj, cfg)
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

    return rows, engine


def summarize_graded(
    rows: list[GradedRow],
    cfg: SportPaceConfig,
    *,
    variant: str = "raw",
) -> dict[str, Any]:
    suffix = "" if variant == "raw" else "_adj"
    spread_key = f"spread_result{suffix}"
    total_key = f"total_result{suffix}"
    bucket_spread = f"spread_bucket{suffix}"
    bucket_total = f"total_bucket{suffix}"

    pool = rows
    if variant == "adj":
        pool = [r for r in rows if getattr(r, "proj_margin_adj") is not None]

    def tally(market: str) -> dict[str, Any]:
        key = spread_key if market == "spread" else total_key
        wins = losses = pushes = 0
        for r in pool:
            res = getattr(r, key)
            if res == "win":
                wins += 1
            elif res == "loss":
                losses += 1
            elif res == "push":
                pushes += 1
        eligible = wins + losses + pushes
        return {
            "picks": eligible,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_pct": round(wins / max(wins + losses, 1) * 100, 2),
            "roi_pct_at_110": roi_at_110(wins, losses),
            "clear_rate": round(eligible / max(len(pool), 1) * 100, 2),
        }

    spread = tally("spread")
    total = tally("total")

    def by_bucket(market: str) -> dict[str, dict[str, Any]]:
        bkey = bucket_spread if market == "spread" else bucket_total
        rkey = spread_key if market == "spread" else total_key
        buckets: dict[str, list[str]] = defaultdict(list)
        for r in pool:
            b = getattr(r, bkey)
            res = getattr(r, rkey)
            if b and res in ("win", "loss", "push"):
                buckets[b].append(res)
        out: dict[str, dict[str, Any]] = {}
        for b, results in sorted(buckets.items()):
            w = sum(1 for x in results if x == "win")
            l = sum(1 for x in results if x == "loss")
            p = sum(1 for x in results if x == "push")
            out[b] = {
                "picks": len(results),
                "wins": w,
                "losses": l,
                "pushes": p,
                "win_pct": round(w / max(w + l, 1) * 100, 2),
                "roi_pct_at_110": roi_at_110(w, l),
            }
        return out

    return {
        "variant": variant,
        "sport": cfg.sport,
        "min_edge_spread": cfg.min_edge_spread,
        "min_edge_total": cfg.min_edge_total,
        "games_with_lines": len(pool),
        "spread": spread,
        "total": total,
        "spread_by_edge_bucket": by_bucket("spread"),
        "total_by_edge_bucket": by_bucket("total"),
    }


def run_backtest_for_sport(sport: str, seasons: list[int]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if sport == "nfl":
        cfg = NFL_PACE_CONFIG
        games = load_nfl_games(seasons)
    elif sport == "ncaaf":
        cfg = NCAAF_PACE_CONFIG
        games = load_ncaaf_games(seasons)
    else:
        raise ValueError(f"unknown sport {sport}")
    injury_ctx = build_injury_context(sport, seasons)
    rows, _ = walk_forward_backtest(games, cfg, injury_ctx=injury_ctx)
    df = pd.DataFrame([asdict(r) for r in rows])
    summary = {
        "sport": sport,
        "seasons": seasons,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "injury_backtest": {
            "nfl_historical": injury_ctx.historical_injuries if sport == "nfl" else False,
            "ncaaf_historical": False,
            "note": (
                "NFL adjusted grades use nflverse weekly injury reports (Out/Doubtful/Questionable)."
                if sport == "nfl"
                else "No free historical NCAAF injury feed; injury-adjusted backtest not run."
            ),
        },
        "unadjusted": summarize_graded(rows, cfg, variant="raw"),
        "injury_adjusted": summarize_graded(rows, cfg, variant="adj"),
    }
    return df, summary


def graded_to_markdown(summary: dict[str, Any]) -> str:
    sport = summary.get("sport", "").upper()
    unadj = summary.get("unadjusted") or {}
    adj = summary.get("injury_adjusted") or {}
    inj = summary.get("injury_backtest") or {}
    lines = [
        f"## {sport} pace model backtest",
        "",
        f"- Seasons: {summary.get('seasons')}",
        f"- Games graded (with closing lines): {unadj.get('games_with_lines')}",
        f"- Min edge spread / total: {unadj.get('min_edge_spread')} / {unadj.get('min_edge_total')} pts",
        f"- Generated: {summary.get('generated_at')}",
        f"- Injury history: {inj.get('note')}",
        "",
        "### Unadjusted — spread (ATS vs close)",
        "",
        _fmt_metrics(unadj.get("spread") or {}),
        "",
        "### Unadjusted — total (O/U vs close)",
        "",
        _fmt_metrics(unadj.get("total") or {}),
        "",
        "### Injury-adjusted — spread",
        "",
        _fmt_metrics(adj.get("spread") or {}),
        "",
        "### Injury-adjusted — total",
        "",
        _fmt_metrics(adj.get("total") or {}),
        "",
        "### Unadjusted spread by edge bucket",
        "",
        _fmt_bucket_table(unadj.get("spread_by_edge_bucket") or {}),
        "",
        "### Injury-adjusted spread by edge bucket",
        "",
        _fmt_bucket_table(adj.get("spread_by_edge_bucket") or {}),
        "",
    ]
    return "\n".join(lines)


def _fmt_metrics(m: dict[str, Any]) -> str:
    return (
        f"| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |"
        f"\n|---:|---:|---:|---:|---:|"
        f"\n| {m.get('picks', 0)} | {m.get('wins', 0)}-{m.get('losses', 0)}-{m.get('pushes', 0)} | "
        f"{m.get('win_pct')}% | {m.get('roi_pct_at_110')}% | {m.get('clear_rate')}% |"
    )


def _fmt_bucket_table(buckets: dict[str, dict[str, Any]]) -> str:
    if not buckets:
        return "_No picks in buckets._"
    hdr = "| Bucket | Picks | W-L-P | Win% | ROI @ -110 |"
    sep = "|---|---:|---:|---:|---:|"
    body = []
    for b, m in buckets.items():
        body.append(
            f"| {b} | {m['picks']} | {m['wins']}-{m['losses']}-{m['pushes']} | "
            f"{m['win_pct']}% | {m['roi_pct_at_110']}% |"
        )
    return "\n".join([hdr, sep, *body])
