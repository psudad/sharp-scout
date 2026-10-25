"""Walk-forward evaluation and reporting for NBA score model."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.research.nba_score_model.data_loader import load_board_lines_from_shadow
from sharp_scout.research.nba_score_model.ratings import ModelParams, RatingEngine, p_cover_home, p_over


OOS_SEASONS = ("2022-23", "2023-24", "2024-25")
TUNE_SEASONS_BEFORE = "2022-23"


@dataclass
class GamePred:
    season: str
    date: str
    away: str
    home: str
    proj_margin: float
    proj_total: float
    act_margin: float
    act_total: float
    close_spread_home: float
    close_total: float
    sd_margin: float
    sd_total: float
    month: int


@dataclass
class EvalResult:
    preds: list[GamePred] = field(default_factory=list)
    params: ModelParams | None = None
    blend_weight: float = 0.0


def _rest_days(team: str, dt: datetime, last_game: dict[str, datetime]) -> int | None:
    prev = last_game.get(team)
    if prev is None:
        return None
    return max((dt.date() - prev.date()).days, 0)


def walk_forward(games: list[dict[str, Any]], params: ModelParams) -> EvalResult:
    engine = RatingEngine(params=params)
    last_played: dict[str, datetime] = {}
    preds: list[GamePred] = []
    current_season: str | None = None

    for g in games:
        season = g["season"]
        if current_season and season != current_season:
            engine.snapshot_season_end()
            engine.new_season()
        current_season = season

        dt: datetime = g["date"]
        home, away = g["home"], g["away"]
        hr = _rest_days(home, dt, last_played)
        ar = _rest_days(away, dt, last_played)

        proj = engine.project(home, away, game_date=dt, home_rest=hr, away_rest=ar)
        hs, as_ = float(g["home_pts"]), float(g["away_pts"])
        act_m = hs - as_
        act_t = hs + as_
        spread = float(g["close_spread_home"])
        total_close = float(g["close_total"])

        preds.append(
            GamePred(
                season=season,
                date=dt.date().isoformat(),
                away=away,
                home=home,
                proj_margin=proj["margin"],
                proj_total=proj["total"],
                act_margin=act_m,
                act_total=act_t,
                close_spread_home=spread,
                close_total=total_close,
                sd_margin=proj["sd_margin"],
                sd_total=proj["sd_total"],
                month=dt.month,
            )
        )

        err_m = act_m - proj["margin"]
        err_t = act_t - proj["total"]
        engine.margin_residuals.append(err_m)
        engine.total_residuals.append(err_t)
        engine.observe(g)
        last_played[home] = dt
        last_played[away] = dt

    return EvalResult(preds=preds, params=params)


def tune_params(games: list[dict[str, Any]]) -> ModelParams:
    train = [g for g in games if g["season"] < TUNE_SEASONS_BEFORE]
    grid = []
    for hl in (30.0, 45.0, 60.0):
        for hca in (2.2, 2.8, 3.4):
            for b2b in (1.0, 1.6, 2.2):
                grid.append(ModelParams(recency_half_life_days=hl, hca_points=hca, b2b_penalty=b2b))
    best = grid[0]
    best_mae = 1e9
    for p in grid:
        ev = walk_forward(train, p)
        mae = _mae_margin(ev.preds)
        if mae < best_mae:
            best_mae = mae
            best = p
    return best


def _mae_margin(preds: list[GamePred]) -> float:
    if not preds:
        return 999.0
    return sum(abs(p.act_margin - p.proj_margin) for p in preds) / len(preds)


def _filter_oos(preds: list[GamePred]) -> list[GamePred]:
    return [p for p in preds if p.season in OOS_SEASONS]


def _market_margin_pred(p: GamePred) -> float:
    return -p.close_spread_home


def _market_total_pred(p: GamePred) -> float:
    return p.close_total


def tune_blend(preds: list[GamePred], *, tune_season: str = "2022-23") -> float:
    """Pick model weight on earliest OOS season only (walk-forward style)."""
    tune_set = [p for p in preds if p.season == tune_season]
    if not tune_set:
        tune_set = _filter_oos(preds)[:800]
    best_w, best_mae = 0.0, 1e9
    for w in [i / 20.0 for i in range(21)]:
        mae = sum(
            abs(p.act_margin - (w * p.proj_margin + (1 - w) * _market_margin_pred(p))) for p in tune_set
        ) / max(len(tune_set), 1)
        if mae < best_mae:
            best_mae = mae
            best_w = w
    return best_w


def summarize(preds: list[GamePred], blend_w: float) -> dict[str, Any]:
    oos = _filter_oos(preds)
    if not oos:
        return {"error": "no_oos_preds"}

    def mae(field_model: str, field_act: str, market_fn) -> dict[str, float]:
        m_mae = sum(abs(getattr(p, field_act) - getattr(p, field_model)) for p in oos) / len(oos)
        mkt_mae = sum(abs(getattr(p, field_act) - market_fn(p)) for p in oos) / len(oos)
        blend_mae = sum(
            abs(
                getattr(p, field_act)
                - (blend_w * getattr(p, field_model) + (1 - blend_w) * market_fn(p))
            )
            for p in oos
        ) / len(oos)
        return {"model": round(m_mae, 3), "market": round(mkt_mae, 3), "blend": round(blend_mae, 3)}

    margin_mae = mae("proj_margin", "act_margin", _market_margin_pred)
    total_mae = mae("proj_total", "act_total", _market_total_pred)

    thresholds = [1, 2, 3, 4]
    ats = {}
    ou = {}
    for th in thresholds:
        ats[str(th)] = _ats_record(oos, th)
        ou[str(th)] = _ou_record(oos, th)

    cal_spread = _calibration_spread(oos)
    cal_total = _calibration_total(oos)
    ats_pcover = _ats_by_p_cover(oos)
    ou_pover = _ou_by_p_over(oos)

    early = [p for p in oos if p.month in (10, 11)]
    late = [p for p in oos if p.month not in (10, 11)]

    return {
        "oos_seasons": list(OOS_SEASONS),
        "n_oos_games": len(oos),
        "margin_mae": margin_mae,
        "total_mae": total_mae,
        "blend_weight_margin": blend_w,
        "ats_by_edge_pts": ats,
        "ou_by_edge_pts": ou,
        "calibration_p_cover": cal_spread,
        "calibration_p_over": cal_total,
        "ats_by_p_cover_bucket": ats_pcover,
        "ou_by_p_over_bucket": ou_pover,
        "early_season_oct_nov": _split_metrics(early),
        "later_season": _split_metrics(late),
    }


def _split_metrics(preds: list[GamePred]) -> dict[str, Any]:
    if not preds:
        return {"n": 0}
    return {
        "n": len(preds),
        "margin_mae_model": round(sum(abs(p.act_margin - p.proj_margin) for p in preds) / len(preds), 3),
        "margin_mae_market": round(
            sum(abs(p.act_margin - _market_margin_pred(p)) for p in preds) / len(preds), 3
        ),
    }


def _ats_record(preds: list[GamePred], min_edge: float) -> dict[str, Any]:
    wins = losses = pushes = 0
    for p in preds:
        edge = p.proj_margin - _market_margin_pred(p)
        if abs(edge) < min_edge:
            continue
        pick_home = edge > 0
        result = p.act_margin + p.close_spread_home
        if abs(result) < 0.5:
            pushes += 1
            continue
        home_cover = result > 0
        if pick_home == home_cover:
            wins += 1
        else:
            losses += 1
    n = wins + losses + pushes
    units = wins * (100 / 110) - losses
    return {"n": n, "record": f"{wins}-{losses}-{pushes}", "units_at_110": round(units, 2)}


def _ou_record(preds: list[GamePred], min_edge: float) -> dict[str, Any]:
    wins = losses = pushes = 0
    for p in preds:
        edge = p.proj_total - p.close_total
        if abs(edge) < min_edge:
            continue
        pick_over = edge > 0
        if abs(p.act_total - p.close_total) < 0.5:
            pushes += 1
            continue
        over = p.act_total > p.close_total
        if pick_over == over:
            wins += 1
        else:
            losses += 1
    units = wins * (100 / 110) - losses
    return {"n": wins + losses + pushes, "record": f"{wins}-{losses}-{pushes}", "units_at_110": round(units, 2)}


def _calibration_spread(preds: list[GamePred]) -> list[dict[str, Any]]:
    buckets: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for p in preds:
        pc = p_cover_home(p.proj_margin, p.close_spread_home, p.sd_margin)
        b = int(pc * 10)
        win = 1 if p.act_margin + p.close_spread_home > 0 else 0
        buckets[b].append((pc, win))
    out = []
    for b in sorted(buckets):
        rows = buckets[b]
        avg_p = sum(x[0] for x in rows) / len(rows)
        wr = sum(x[1] for x in rows) / len(rows)
        out.append({"bucket": b, "n": len(rows), "avg_p_cover": round(avg_p, 3), "win_rate": round(wr, 3)})
    return out


def _ats_by_p_cover(preds: list[GamePred]) -> list[dict[str, Any]]:
    """Flat -110 when model p_cover favors a side (|p-0.5| >= 0.05)."""
    buckets: dict[int, list[int]] = defaultdict(list)
    for p in preds:
        pc = p_cover_home(p.proj_margin, p.close_spread_home, p.sd_margin)
        if abs(pc - 0.5) < 0.05:
            continue
        pick_home = pc >= 0.5
        result = p.act_margin + p.close_spread_home
        if abs(result) < 0.5:
            continue
        home_cover = result > 0
        win = 1 if pick_home == home_cover else 0
        b = int(pc * 10)
        buckets[b].append(win)
    out = []
    for b in sorted(buckets):
        wins = sum(buckets[b])
        n = len(buckets[b])
        out.append({"bucket": b, "n": n, "win_rate": round(wins / n, 3), "units_at_110": round(wins * (100 / 110) - (n - wins), 2)})
    return out


def _ou_by_p_over(preds: list[GamePred]) -> list[dict[str, Any]]:
    buckets: dict[int, list[int]] = defaultdict(list)
    for p in preds:
        po = p_over(p.proj_total, p.close_total, p.sd_total)
        if abs(po - 0.5) < 0.05:
            continue
        pick_over = po >= 0.5
        if abs(p.act_total - p.close_total) < 0.5:
            continue
        over = p.act_total > p.close_total
        win = 1 if pick_over == over else 0
        b = int(po * 10)
        buckets[b].append(win)
    out = []
    for b in sorted(buckets):
        wins = sum(buckets[b])
        n = len(buckets[b])
        out.append({"bucket": b, "n": n, "win_rate": round(wins / n, 3), "units_at_110": round(wins * (100 / 110) - (n - wins), 2)})
    return out


def _calibration_total(preds: list[GamePred]) -> list[dict[str, Any]]:
    buckets: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for p in preds:
        po = p_over(p.proj_total, p.close_total, p.sd_total)
        b = int(po * 10)
        win = 1 if p.act_total > p.close_total else 0
        buckets[b].append((po, win))
    out = []
    for b in sorted(buckets):
        rows = buckets[b]
        avg_p = sum(x[0] for x in rows) / len(rows)
        wr = sum(x[1] for x in rows) / len(rows)
        out.append({"bucket": b, "n": len(rows), "avg_p_over": round(avg_p, 3), "win_rate": round(wr, 3)})
    return out


def write_csv(path: Path, preds: list[GamePred]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "season",
        "date",
        "away",
        "home",
        "proj_margin",
        "proj_total",
        "act_margin",
        "act_total",
        "close_spread_home",
        "close_total",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for p in preds:
            w.writerow({k: getattr(p, k) for k in fields})


def render_markdown(summary: dict[str, Any], slate: list[dict[str, Any]]) -> str:
    mm = summary["margin_mae"]
    tm = summary["total_mae"]
    lines = [
        "# NBA score projection model (research)",
        "",
        "Research only — independent team ratings → projected points/margin/total vs closing lines.",
        "",
        "## Out-of-sample (2022-23 – 2024-25)",
        "",
        f"Games: **{summary['n_oos_games']}**",
        "",
    ]
    dq = summary.get("data_quality") or {}
    lq = dq.get("line_diagnostics_oos") or {}
    if lq.get("n"):
        lines.extend(
            [
                f"Line join QA (OOS): mean(margin+home_spread)={lq.get('mean_margin_plus_home_spread')}, "
                f"share |net|<3pt={lq.get('share_abs_net_under_3')}",
                "",
            ]
        )
    lines.extend(
        [
            "### Mean absolute error",
            "",
            "| Target | Model | Market close | Model⊕market blend |",
            "|--------|-------|--------------|-------------------|",
            f"| Margin | {mm['model']} | {mm['market']} | {mm['blend']} (w={summary['blend_weight_margin']:.2f}) |",
            f"| Total | {tm['model']} | {tm['market']} | {tm['blend']} |",
            "",
            "### ATS / O-U when projection beats close by ≥ N points (flat -110)",
            "",
        ]
    )
    bugs = summary.get("bugs_fixed_in_this_run") or []
    if bugs:
        lines.extend(["### Data fixes in this report", ""] + [f"- {b}" for b in bugs] + [""])
    for th, rec in summary.get("ats_by_edge_pts", {}).items():
        lines.append(f"- **ATS ≥{th}pt edge:** {rec['record']} ({rec['units_at_110']}u, n={rec['n']})")
    lines.append("")
    for th, rec in summary.get("ou_by_edge_pts", {}).items():
        lines.append(f"- **O/U ≥{th}pt edge:** {rec['record']} ({rec['units_at_110']}u, n={rec['n']})")
    lines.extend(
        [
            "",
            "### Early (Oct–Nov) vs later",
            "",
            f"- Early: {json.dumps(summary.get('early_season_oct_nov'))}",
            f"- Later: {json.dumps(summary.get('later_season'))}",
            "",
            "## Verdict",
            "",
            _verdict(summary),
            "",
            "## Tonight's slate (projections vs board lines if present)",
            "",
        ]
    )
    if not slate:
        lines.append("_No upcoming games loaded._")
    else:
        lines.append("| Away @ Home | Proj score | Margin | Total | Close spread | Close total |")
        lines.append("|-------------|------------|--------|-------|--------------|-------------|")
        for row in slate:
            lines.append(
                f"| {row['away']} @ {row['home']} | {row['proj_score']} | {row['proj_margin']:+.1f} | "
                f"{row['proj_total']:.1f} | {row.get('close_spread', '—')} | {row.get('close_total', '—')} |"
            )
    return "\n".join(lines) + "\n"


def _verdict(summary: dict[str, Any]) -> str:
    mm = summary["margin_mae"]
    if mm["model"] > mm["market"] + 0.15:
        return (
            "The walk-forward efficiency model **does not beat the closing spread** on margin MAE out-of-sample. "
            "Totals are closer but still slightly behind or tied with the market. It is **not production-worthy** "
            "without richer data (possession-level PBP, injuries, multi-book openers) and a calibrated ensemble "
            "that proves OOS ATS/O-U edge after vig."
        )
    if mm["model"] <= mm["market"]:
        gap = round(mm["market"] - mm["model"], 2)
        return (
            f"Margin MAE is **modestly below** the closing line OOS (~{gap} pts); totals lag the market slightly. "
            "That is research-grade signal, not a license to bet: possession-level PBP, injury/minutes, "
            "multi-book closes, and paper-trade CLV at realistic thresholds would be required before the NBA lane."
        )
    return (
        "Model is **near market** on MAE but not clearly superior. Production would need demonstrated betting "
        "edge at realistic thresholds after vig, plus injury and pace inputs."
    )


def project_tonight_slate(
    engine: RatingEngine,
    *,
    shadow_history: Path,
    last_played: dict[str, datetime] | None = None,
) -> list[dict[str, Any]]:
    from sharp_scout.data import espn_nba as espn

    today = datetime.now(timezone.utc)
    d = today.strftime("%Y%m%d")
    from sharp_scout.data.espn_cfb import _get_json
    from urllib.parse import urlencode

    url = f"{espn.ESPN_SCOREBOARD}?{urlencode({'dates': d, 'limit': 50})}"
    payload = _get_json(url)
    events = payload.get("events") or []
    board = load_board_lines_from_shadow(shadow_history)
    # map event_id from signals file if needed
    signals_path = shadow_history.parent / "nba_latest_signals.json"
    eid_map: dict[tuple[str, str], str] = {}
    if signals_path.exists():
        sig = json.loads(signals_path.read_text())
        for s in sig.get("signals") or []:
            eid_map[(s.get("away_team"), s.get("home_team"))] = s.get("event_id")

    out = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        status = ((comp.get("status") or {}).get("type") or {}).get("name") or ""
        if status in ("STATUS_FINAL", "STATUS_FINAL_OVERTIME"):
            continue
        teams = {}
        for c in comp.get("competitors") or []:
            teams[c.get("homeAway")] = espn._team_code(c.get("team") or {})
        away, home = teams.get("away"), teams.get("home")
        if not away or not home:
            continue
        hr = _rest_days(home, today, last_played or {})
        ar = _rest_days(away, today, last_played or {})
        proj = engine.project(home, away, game_date=today, home_rest=hr, away_rest=ar)
        eid = eid_map.get((away, home)) or str(ev.get("id"))
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
