"""Stage-by-stage walk-forward evaluation and market / CLV tests (v2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sharp_scout.research.nba_score_model.box_scores import estimate_poss_from_points
from sharp_scout.research.nba_score_model.evaluate import (
    OOS_SEASONS,
    TUNE_SEASONS_BEFORE,
    GamePred,
    _ats_record,
    _calibration_spread,
    _calibration_total,
    _filter_oos,
    _ou_record,
    _rest_days,
    tune_blend,
    walk_forward,
)
from sharp_scout.research.nba_score_model.ratings import ModelParams, RatingEngine
from sharp_scout.research.nba_score_model.teams_geo import travel_miles
from sharp_scout.research.nba_score_model.v2_engine import V2Engine, V2Params


STAGE_NAMES = {
    0: "v1_baseline (score-only EMA, no opp ridge)",
    1: "possession ridge (ESPN box OR poss est)",
    2: "+ preseason priors (1/3 mean regress)",
    3: "+ schedule (rest/B2B/3-in-4/travel/altitude)",
    4: "+ player minutes layer (0-min injury proxy)",
}


@dataclass
class StageResult:
    stage: int
    name: str
    preds: list[GamePred] = field(default_factory=list)
    blend_w: float = 0.0


def _game_context(
    g: dict[str, Any],
    *,
    last_played: dict[str, datetime],
    team_last_site: dict[str, str],
    team_game_dates: dict[str, list[datetime]],
) -> dict[str, Any]:
    dt: datetime = g["date"]
    home, away = g["home"], g["away"]
    hr = _rest_days(home, dt, last_played)
    ar = _rest_days(away, dt, last_played)

    def games_in_last_days(team: str, days: int) -> int:
        hist = team_game_dates.get(team, [])
        cutoff = dt - timedelta(days=days)
        return sum(1 for d in hist if cutoff < d < dt)

    home_3in4 = games_in_last_days(home, 4) >= 2
    away_3in4 = games_in_last_days(away, 4) >= 2
    home_from = team_last_site.get(home, home)
    away_from = team_last_site.get(away, away)
    return {
        "home_rest": hr,
        "away_rest": ar,
        "home_b2b": hr is not None and hr <= 1,
        "away_b2b": ar is not None and ar <= 1,
        "home_3in4": home_3in4,
        "away_3in4": away_3in4,
        "home_travel_mi": travel_miles(home_from, home) if home_from != home else 0.0,
        "away_travel_mi": travel_miles(away_from, away) if away_from != away else 0.0,
    }


def _ensure_poss_fields(g: dict[str, Any]) -> None:
    if g.get("game_poss"):
        return
    hs, as_ = float(g["home_pts"]), float(g["away_pts"])
    poss = estimate_poss_from_points(hs, as_)
    g["game_poss"] = poss
    g["home_poss"] = poss
    g["away_poss"] = poss


def walk_forward_v2(games: list[dict[str, Any]], params: V2Params, *, stage: int) -> list[GamePred]:
    engine = V2Engine(params=params, stage=max(stage, 1))
    last_played: dict[str, datetime] = {}
    team_last_site: dict[str, str] = {}
    team_game_dates: dict[str, list[datetime]] = {}
    preds: list[GamePred] = []
    current_season: str | None = None

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
        home, away = g["home"], g["away"]
        proj = engine.project(
            home,
            away,
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
        hs, as_ = float(g["home_pts"]), float(g["away_pts"])
        open_sp = float(g.get("open_spread_home", g["close_spread_home"]))
        open_tot = float(g.get("open_total", g["close_total"]))
        preds.append(
            GamePred(
                season=season,
                date=dt.date().isoformat(),
                away=away,
                home=home,
                proj_margin=proj["margin"],
                proj_total=proj["total"],
                act_margin=hs - as_,
                act_total=hs + as_,
                close_spread_home=float(g["close_spread_home"]),
                close_total=float(g["close_total"]),
                open_spread_home=open_sp,
                open_total=open_tot,
                yahoo_spread_stake_pct=g.get("yahoo_spread_stake_pct"),
                sd_margin=proj["sd_margin"],
                sd_total=proj["sd_total"],
                month=dt.month,
                source=g.get("source"),
            )
        )

        err_m = (hs - as_) - proj["margin"]
        err_t = (hs + as_) - proj["total"]
        engine.margin_residuals.append(err_m)
        engine.total_residuals.append(err_t)
        engine.observe(g, ctx=ctx)

        last_played[home] = dt
        last_played[away] = dt
        team_last_site[home] = home
        team_last_site[away] = away
        team_game_dates.setdefault(home, []).append(dt)
        team_game_dates.setdefault(away, []).append(dt)

    return preds


def tune_v2_params(games: list[dict[str, Any]], *, stage: int = 3) -> V2Params:
    train = [g for g in games if g["season"] < TUNE_SEASONS_BEFORE]
    grid: list[V2Params] = []
    for lam in (1.5, 3.0):
        for hl in (40.0,):
            for hca in (2.0, 2.25):
                grid.append(V2Params(ridge_lambda=lam, recency_half_life_days=hl, hca_points=hca))
    best = grid[0]
    best_mae = 1e9
    for p in grid:
        preds = walk_forward_v2(train, p, stage=stage)
        mae = sum(abs(p.act_margin - p.proj_margin) for p in preds) / max(len(preds), 1)
        if mae < best_mae:
            best_mae = mae
            best = p
    return best


def _open_margin(p: GamePred) -> float:
    sp = p.open_spread_home if p.open_spread_home is not None else p.close_spread_home
    return -float(sp)


def _close_margin(p: GamePred) -> float:
    return -p.close_spread_home


def mae_table(preds: list[GamePred], blend_w: float) -> dict[str, dict[str, float]]:
    oos = _filter_oos(preds)
    if not oos:
        return {}

    def _mae(field_model: str, field_act: str, market_fn) -> dict[str, float]:
        m_mae = sum(abs(getattr(p, field_act) - getattr(p, field_model)) for p in oos) / len(oos)
        mkt_mae = sum(abs(getattr(p, field_act) - market_fn(p)) for p in oos) / len(oos)
        blend_mae = sum(
            abs(getattr(p, field_act) - (blend_w * getattr(p, field_model) + (1 - blend_w) * market_fn(p)))
            for p in oos
        ) / len(oos)
        return {"model": round(m_mae, 3), "market": round(mkt_mae, 3), "blend": round(blend_mae, 3)}

    return {
        "margin": _mae("proj_margin", "act_margin", _close_margin),
        "margin_vs_open": _mae("proj_margin", "act_margin", _open_margin),
        "total": _mae("proj_total", "act_total", lambda p: p.close_total),
        "total_vs_open": _mae(
            "proj_total", "act_total", lambda p: float(p.open_total if p.open_total is not None else p.close_total)
        ),
    }


def run_all_stages(games: list[dict[str, Any]], v2_params: V2Params) -> list[StageResult]:
    out: list[StageResult] = []
    # Stage 0: v1
    v1_params = ModelParams(recency_half_life_days=30.0, hca_points=2.2, b2b_penalty=1.6)
    v1 = walk_forward(games, v1_params).preds
    bw0 = tune_blend(v1)
    out.append(StageResult(0, STAGE_NAMES[0], v1, bw0))
    for stage in (1, 2, 3, 4):
        preds = walk_forward_v2(games, v2_params, stage=stage)
        bw = tune_blend(preds)
        out.append(StageResult(stage, STAGE_NAMES[stage], preds, bw))
    return out


def summarize_stage(sr: StageResult) -> dict[str, Any]:
    table = mae_table(sr.preds, sr.blend_w)
    oos = _filter_oos(sr.preds)
    return {
        "stage": sr.stage,
        "name": sr.name,
        "n_oos": len(oos),
        "blend_weight_margin": sr.blend_w,
        "mae": table,
        "ats_close_ge1": _ats_record(oos, 1.0),
        "ats_open_ge1": _ats_vs_open(oos, 1.0),
        "ou_close_ge1": _ou_record(oos, 1.0),
        "calibration_p_cover": _calibration_spread(oos),
        "calibration_p_over": _calibration_total(oos),
    }


def _ats_vs_open(preds: list[GamePred], min_edge: float) -> dict[str, Any]:
    wins = losses = pushes = 0
    for p in preds:
        open_m = _open_margin(p)
        edge = p.proj_margin - open_m
        if abs(edge) < min_edge:
            continue
        pick_home = edge > 0
        result = p.act_margin + p.close_spread_home
        if abs(result) < 0.5:
            pushes += 1
            continue
        if pick_home == (result > 0):
            wins += 1
        else:
            losses += 1
    units = wins * (100 / 110) - losses
    return {"n": wins + losses + pushes, "record": f"{wins}-{losses}-{pushes}", "units_at_110": round(units, 2)}


def market_move_analysis(preds: list[GamePred]) -> dict[str, Any]:
    oos = [p for p in _filter_oos(preds) if p.open_spread_home is not None]
    if not oos:
        return {"n": 0}
    # Yahoo pregame often equals close; only score moves with |open-close| >= 0.5
    oos_move = [p for p in oos if abs(p.close_spread_home - p.open_spread_home) >= 0.5]
    spread_hits = spread_n = 0
    total_hits = total_n = 0
    spread_edges: list[tuple[float, float]] = []
    total_edges: list[tuple[float, float]] = []
    combo_hits = combo_n = 0
    for p in oos_move:
        open_m = _open_margin(p)
        close_m = _close_margin(p)
        move_m = close_m - open_m
        model_edge = p.proj_margin - open_m
        if abs(model_edge) >= 1.0:
            spread_n += 1
            if (model_edge > 0) == (move_m > 0):
                spread_hits += 1
            spread_edges.append((model_edge, move_m))
    for p in oos:
        open_tot = float(p.open_total if p.open_total is not None else p.close_total)
        move_t = p.close_total - open_tot
        if abs(move_t) < 0.5:
            continue
        model_t_edge = p.proj_total - open_tot
        if abs(model_t_edge) >= 1.0:
            total_n += 1
            if (model_t_edge > 0) == (move_t > 0):
                total_hits += 1
            total_edges.append((model_t_edge, move_t))
    for p in oos_move:
        open_m = _open_margin(p)
        close_m = _close_margin(p)
        move_m = close_m - open_m
        model_edge = p.proj_margin - open_m
        stake = p.yahoo_spread_stake_pct
        if stake is not None and abs(model_edge) >= 1.0:
            sharp_home = stake >= 50.0
            model_home = model_edge > 0
            combo_n += 1
            if model_home == sharp_home and (model_home == (move_m > 0)):
                combo_hits += 1

    def _corr(pairs: list[tuple[float, float]]) -> float | None:
        if len(pairs) < 30:
            return None
        xs = [a for a, _ in pairs]
        ys = [b for _, b in pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        num = sum((x - mx) * (y - my) for x, y in pairs)
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        return round(num / den, 3) if den else None

    return {
        "n_oos": len(oos),
        "n_oos_with_open_close_move": len(oos_move),
        "spread_move_hit_rate_ge1": round(spread_hits / spread_n, 3) if spread_n else None,
        "spread_move_n_ge1": spread_n,
        "spread_move_corr_ge1": _corr(spread_edges),
        "total_move_hit_rate_ge1": round(total_hits / total_n, 3) if total_n else None,
        "total_move_n_ge1": total_n,
        "total_move_corr_ge1": _corr(total_edges),
        "combo_model_sharp_stake_spread": {
            "n": combo_n,
            "hit_rate": round(combo_hits / combo_n, 3) if combo_n else None,
        },
    }


def render_v2_markdown(
    stages: list[dict[str, Any]],
    sbr_clv: dict[str, Any],
    slate: list[dict[str, Any]],
    *,
    final_stage: int = 3,
) -> str:
    lines = [
        "# NBA score projection model v2 (research)",
        "",
        "Walk-forward staged build — MAE after each layer (OOS 2022-23 – 2024-25).",
        "",
        "**v1 baseline weakness:** score-derived pseudo-possessions, no opponent-adjusted ridge, "
        "and PPP/ORtg scale mix — explains ~13.4 margin MAE vs ~10.4 close.",
        "",
        "## Stage MAE ladder",
        "",
        "| Stage | Margin MAE (model / close / blend) | Total MAE (model / close / blend) | Blend w |",
        "|-------|-----------------------------------|-----------------------------------|---------|",
    ]
    for s in stages:
        mm = s["mae"]["margin"]
        tm = s["mae"]["total"]
        lines.append(
            f"| {s['stage']}: {s['name'][:48]} | {mm['model']} / {mm['market']} / {mm['blend']} | "
            f"{tm['model']} / {tm['market']} / {tm['blend']} | {s['blend_weight_margin']:.2f} |"
        )
    fs = next(x for x in stages if x["stage"] == final_stage)
    lines.extend(
        [
            "",
            f"## Final stage ({final_stage}) vs open & close",
            "",
            f"- Margin MAE vs **open**: {fs['mae']['margin_vs_open']['market']}",
            f"- Margin MAE vs **close**: {fs['mae']['margin']['market']}",
            "",
            "### ATS / O-U (≥1pt edge vs close / vs open)",
            "",
            f"- ATS vs close: {fs['ats_close_ge1']}",
            f"- ATS vs open: {fs['ats_open_ge1']}",
            f"- O/U vs close: {fs['ou_close_ge1']}",
            "",
            "## CLV audit — SBR true openers (2010-11 – 2020-21, walk-forward stage 3)",
            "",
            "_Yahoo `pregame_odds` ≈ close → prior ~90% move hits were **artifact** (subset + pseudo-open)._",
            "",
            f"{sbr_clv}",
            "",
            "## Verdict",
            "",
            _v2_verdict(stages, final_stage=final_stage),
            "",
            "## Tonight's slate (final stage engine)",
            "",
        ]
    )
    if slate:
        lines.append("| Away @ Home | Proj | Margin | Total | Close spr/tot |")
        lines.append("|-------------|------|--------|-------|---------------|")
        for row in slate:
            lines.append(
                f"| {row['away']} @ {row['home']} | {row['proj_score']} | {row['proj_margin']:+.1f} | "
                f"{row['proj_total']:.1f} | {row.get('close_spread')} / {row.get('close_total')} |"
            )
    else:
        lines.append("_No slate._")
    return "\n".join(lines) + "\n"


def _v2_verdict(stages: list[dict[str, Any]], *, final_stage: int = 3) -> str:
    s0 = next(x for x in stages if x["stage"] == 0)
    sf = next(x for x in stages if x["stage"] == final_stage)
    m0 = s0["mae"]["margin"]["model"]
    mf = sf["mae"]["margin"]["model"]
    tf = sf["mae"]["total"]["model"]
    close_m = sf["mae"]["margin"]["market"]
    close_t = sf["mae"]["total"]["market"]
    return (
        f"Margin improved **{m0:.3f}** → **{mf:.3f}** (stage {final_stage}) vs close **{close_m:.3f}** — near market, not beatable. "
        f"Totals were broken by ridge without a league-mean intercept (~20 MAE); fixed to **{tf:.3f}** vs close **{close_t:.3f}** "
        "(pace×ORtg path). **SBR CLV** (true openers): ~51% line-move direction, negative ATS vs opener at 1/2/3+ pt edges — "
        "no credible CLV edge; Yahoo ~90% was pseudo-open/selection. Stage 4 player proxy is margin-only (+0.01 MAE); skip for totals."
    )
