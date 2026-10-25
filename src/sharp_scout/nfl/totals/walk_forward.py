"""Strict walk-forward season backtest for NFL simulation totals."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sharp_scout.data.nflfastr import load_pbp, load_schedules
from sharp_scout.nfl.totals.blend import blend_total, choose_blend_weight
from sharp_scout.nfl.totals.calibrate import (
    mean_signed_vs_close,
    walk_forward_total_bias,
)
from sharp_scout.nfl.totals.rates import build_team_drive_rates, team_rates
from sharp_scout.nfl.totals.simulate import simulate_nfl_total
from sharp_scout.utils.odds import american_to_implied_prob, normalize_team


@dataclass
class GameInput:
    season: int
    week: int
    kickoff_et: str
    away: str
    home: str
    final_total: float
    close_line: float
    close_price: int | None
    scan_line: float | None
    scan_price: int | None
    old_model_total: float | None
    old_pick: str | None
    old_result_close: str | None
    old_units_110: float | None
    old_units_close: float | None


@dataclass
class GameResult:
    row: dict[str, Any] = field(default_factory=dict)


def _parse_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_int_price(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _parse_kickoff_sort(key: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(key.strip(), fmt)
        except ValueError:
            continue
    return datetime.min


def load_games_from_csv(csv_path: Path) -> list[GameInput]:
    out: list[GameInput] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            close = _parse_float(row.get("pinnacle_close_line")) or _parse_float(
                row.get("market_total")
            )
            if close is None:
                continue
            ft = _parse_float(row.get("final_total"))
            if ft is None:
                continue
            away = normalize_team(row.get("away") or "", "nfl") or (row.get("away") or "")
            home = normalize_team(row.get("home") or "", "nfl") or (row.get("home") or "")
            out.append(
                GameInput(
                    season=2026,
                    week=int(row.get("week") or 0),
                    kickoff_et=str(row.get("kickoff_et") or ""),
                    away=away,
                    home=home,
                    final_total=ft,
                    close_line=close,
                    close_price=_parse_int_price(row.get("pinnacle_close_price")),
                    scan_line=_parse_float(row.get("market_total")),
                    scan_price=_parse_int_price(row.get("pinnacle_price_at_scan")),
                    old_model_total=_parse_float(row.get("model_total")),
                    old_pick=str(row.get("pick") or "").lower() or None,
                    old_result_close=str(row.get("result_vs_close") or row.get("result") or "")[
                        :1
                    ].upper()
                    or None,
                    old_units_110=_parse_float(row.get("units_at_110")),
                    old_units_close=_parse_float(row.get("units_vs_close")),
                )
            )
    return out


def _game_key(g: GameInput) -> str:
    return f"{g.season}:{g.week}:{g.away}@{g.home}:{g.kickoff_et}"


def append_completed_from_schedules(
    games: list[GameInput], *, season: int = 2026
) -> list[GameInput]:
    """Add finished 2026 games not already in the CSV."""
    have = {_game_key(g) for g in games}
    sched = load_schedules([season])
    if sched.empty:
        return games
    extra: list[GameInput] = []
    for _, r in sched.iterrows():
        try:
            hs, as_ = r.get("home_score"), r.get("away_score")
            if hs is None or as_ is None or (isinstance(hs, float) and math.isnan(hs)):
                continue
            total_line = r.get("total_line")
            if total_line is None or (isinstance(total_line, float) and math.isnan(total_line)):
                continue
        except (TypeError, ValueError):
            continue
        away = normalize_team(str(r.get("away_team") or ""), "nfl")
        home = normalize_team(str(r.get("home_team") or ""), "nfl")
        week = int(r.get("week") or 0)
        gday = r.get("gameday")
        kick = str(gday)[:10] if gday is not None else ""
        gi = GameInput(
            season=season,
            week=week,
            kickoff_et=kick,
            away=away or "",
            home=home or "",
            final_total=float(as_) + float(hs),
            close_line=float(total_line),
            close_price=None,
            scan_line=float(total_line),
            scan_price=None,
            old_model_total=None,
            old_pick=None,
            old_result_close=None,
            old_units_110=None,
            old_units_close=None,
        )
        key = _game_key(gi)
        if key not in have and f"{season}:{week}:{gi.away}@{gi.home}" not in {
            f"{g.season}:{g.week}:{g.away}@{g.home}" for g in games
        }:
            # dedupe by matchup+week only if kickoff missing
            dup = any(
                g.season == gi.season and g.week == gi.week and g.away == gi.away and g.home == gi.home
                for g in games
            )
            if not dup:
                extra.append(gi)
                have.add(key)
    games.extend(extra)
    games.sort(key=lambda g: (_parse_kickoff_sort(g.kickoff_et), g.week, g.away))
    return games


def _pbp_before_week(pbp: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    if pbp.empty:
        return pbp
    s = pd.to_numeric(pbp["season"], errors="coerce")
    w = pd.to_numeric(pbp["week"], errors="coerce")
    return pbp[(s < season) | ((s == season) & (w < week))].copy()


def _grade(side: str, line: float, final_total: float) -> str:
    if final_total > line:
        winner = "over"
    elif final_total < line:
        winner = "under"
    else:
        return "P"
    return "W" if side == winner else "L"


def _units(result: str, american: int | None) -> float:
    if result == "P":
        return 0.0
    if result == "L":
        return -1.0
    if american is None:
        return 0.9090909090909091
    if american >= 0:
        return american / 100.0
    return 100.0 / abs(american)


def _ev(p_win: float, american: int | None) -> float:
    if american is None:
        american = -110
    imp = american_to_implied_prob(float(american))
    # edge as p_true - implied (matches pipeline "edge" scale approximately)
    return p_win - imp


def _prob_bucket(p: float) -> str:
    pct = p * 100
    if pct < 55:
        return "50-55%"
    if pct < 60:
        return "55-60%"
    return "60%+"


def _gap_bucket(gap: float) -> str:
    g = abs(gap)
    if g < 2:
        return "0-2"
    if g < 4:
        return "2-4"
    if g < 6:
        return "4-6"
    return "6+"


def _result_keys(prefix: str) -> tuple[str, str, str]:
    if prefix == "old":
        return "old_result_close", "old_units_close_110", "old_units_close_actual"
    return (
        f"{prefix}_result_close",
        f"{prefix}_units_close_110",
        f"{prefix}_units_close_actual",
    )


def _summarize_records(rows: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    w = l = p = 0
    u110 = uact = 0.0
    rk, u110k, uactk = _result_keys(prefix)
    for r in rows:
        res = r.get(rk)
        if res == "W":
            w += 1
        elif res == "L":
            l += 1
        elif res == "P":
            p += 1
        if r.get(u110k) is not None:
            u110 += float(r[u110k])
        elif res:
            u110 += _units(str(res), -110)
        if r.get(uactk) is not None:
            uact += float(r[uactk])
        elif res and prefix != "old":
            uact += float(r.get(f"{prefix}_units_close_actual") or 0)
    return {
        "record": f"{w}-{l}-{p}",
        "units_at_110": round(u110, 2),
        "units_at_close_price": round(uact, 2),
    }


def _mae(vals: list[float], finals: list[float]) -> float:
    if not vals:
        return 0.0
    return float(sum(abs(v - f) for v, f in zip(vals, finals, strict=True)) / len(vals))


def run_walk_forward_backtest(
    games: list[GameInput],
    *,
    pbp: pd.DataFrame | None = None,
    n_sims: int = 4000,
    min_blend_history: int = 12,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if pbp is None:
        pbp = load_pbp([2025, 2026])

    rates_cache: dict[tuple[int, int], Any] = {}
    hist_sim_raw: list[float] = []
    hist_sim_cal: list[float] = []
    hist_mkt: list[float] = []
    hist_fin: list[float] = []

    per_game: list[dict[str, Any]] = []

    for gi in games:
        cache_key = (gi.season, gi.week)
        if cache_key not in rates_cache:
            hist_pbp = _pbp_before_week(pbp, gi.season, gi.week)
            rates_cache[cache_key] = build_team_drive_rates(hist_pbp)
        rates = rates_cache[cache_key]
        hr = team_rates(rates, gi.home)
        ar = team_rates(rates, gi.away)

        bias = walk_forward_total_bias(hist_sim_raw, hist_fin)

        if len(hist_sim_cal) >= min_blend_history:
            w_sim, _, _, _ = choose_blend_weight(hist_sim_cal, hist_mkt, hist_fin)
        else:
            w_sim = 0.0

        seed = gi.week * 10000 + hash(f"{gi.away}@{gi.home}") % 10000
        scan_line = gi.scan_line if gi.scan_line is not None else gi.close_line
        scan_price = gi.scan_price if gi.scan_price is not None else -110
        sim = simulate_nfl_total(
            home_team=gi.home,
            away_team=gi.away,
            home_rates=hr,
            away_rates=ar,
            market_line=scan_line,
            n_sims=n_sims,
            seed=seed,
        )
        sim_median_raw = float(sim.sim_median)
        sim_median_cal = sim_median_raw - bias
        blended = blend_total(sim_median_cal, gi.close_line, weight_sim=w_sim)
        sim_side = "over" if sim_median_cal >= gi.close_line else "under"
        blend_side = "over" if blended >= gi.close_line else "under"
        if sim.total_samples is not None:
            totals = sim.total_samples - bias
            sim_p_close = float(
                np.mean(totals > gi.close_line)
                if sim_side == "over"
                else np.mean(totals < gi.close_line)
            )
            sim_p_scan = float(
                np.mean(totals > scan_line)
                if sim_side == "over"
                else np.mean(totals < scan_line)
            )
        else:
            sim_p_close = float(sim.p_over if sim_side == "over" else (sim.p_under or 0))
            sim_p_scan = sim_p_close
        close_price = gi.close_price if gi.close_price is not None else -110

        sim_res = _grade(sim_side, gi.close_line, gi.final_total)
        blend_res = _grade(blend_side, gi.close_line, gi.final_total)
        sim_res_scan = _grade(sim_side, scan_line, gi.final_total)
        blend_res_scan = _grade(blend_side, scan_line, gi.final_total)

        old_side = gi.old_pick if gi.old_pick in ("over", "under") else None
        old_res = (
            _grade(old_side, gi.close_line, gi.final_total) if old_side else None
        )

        gap = blended - gi.close_line
        sim_gap = sim_median_cal - gi.close_line
        sim_side_scan = "over" if sim_median_cal >= scan_line else "under"
        if sim.total_samples is not None:
            totals = sim.total_samples - bias
            sim_p_scan_side = float(
                np.mean(totals > scan_line)
                if sim_side_scan == "over"
                else np.mean(totals < scan_line)
            )
        else:
            sim_p_scan_side = sim_p_scan

        ev_scan = _ev(sim_p_scan_side, scan_price)
        card_pass = (
            sim_p_scan_side >= 0.50
            and 0.04 <= ev_scan <= 0.12
            and sim_side_scan in ("over", "under")
        )

        row = {
            "season": gi.season,
            "week": gi.week,
            "kickoff_et": gi.kickoff_et,
            "away": gi.away,
            "home": gi.home,
            "final_total": gi.final_total,
            "pinnacle_close_line": gi.close_line,
            "pinnacle_close_price": close_price,
            "scan_line": scan_line,
            "scan_price": gi.scan_price,
            "walk_forward_bias": round(bias, 3),
            "blend_weight_sim": round(w_sim, 3),
            "sim_median_raw": round(sim_median_raw, 2),
            "sim_median": round(sim_median_cal, 2),
            "sim_mean_raw": round(sim.sim_mean, 2),
            "blended_projection": round(blended, 2),
            "sim_lean": sim_side,
            "sim_lean_scan": sim_side_scan,
            "blend_lean": blend_side,
            "sim_p_side_close": round(sim_p_close, 4),
            "sim_p_side": round(sim_p_scan_side, 4),
            "sim_gap_pts": round(sim_gap, 2),
            "blend_gap_pts": round(gap, 2),
            "sim_result_close": sim_res,
            "blend_result_close": blend_res,
            "sim_result_scan": sim_res_scan,
            "blend_result_scan": blend_res_scan,
            "sim_units_close_110": _units(sim_res, -110),
            "blend_units_close_110": _units(blend_res, -110),
            "sim_units_close_actual": _units(sim_res, close_price),
            "blend_units_close_actual": _units(blend_res, close_price),
            "old_model_total": gi.old_model_total,
            "old_pick": old_side,
            "old_result_close": old_res,
            "old_units_close_110": _units(old_res, -110) if old_res else None,
            "old_units_close_actual": gi.old_units_close,
            "card_gate_pass": card_pass,
            "card_ev_at_scan": round(ev_scan, 4),
        }
        per_game.append(row)

        hist_sim_raw.append(sim_median_raw)
        hist_sim_cal.append(sim_median_cal)
        hist_mkt.append(gi.close_line)
        hist_fin.append(gi.final_total)

    finals = [g.final_total for g in games]
    closes = [g.close_line for g in games]
    sim_meds_raw = [r["sim_median_raw"] for r in per_game]
    sim_meds = [r["sim_median"] for r in per_game]
    blend_proj = [r["blended_projection"] for r in per_game]
    mkt_lines = [g.close_line for g in games]
    old_mod = [r["old_model_total"] for r in per_game if r["old_model_total"] is not None]
    old_fin = [
        r["final_total"] for r in per_game if r["old_model_total"] is not None
    ]

    card_rows = [r for r in per_game if r["card_gate_pass"]]

    def _card_gate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        w = l = p = 0
        u110 = 0.0
        for r in rows:
            res = r.get("sim_result_scan")
            if res == "W":
                w += 1
            elif res == "L":
                l += 1
            elif res == "P":
                p += 1
            price = r.get("scan_price") if r.get("scan_price") is not None else -110
            u110 += _units(str(res), -110) if res else 0.0
        return {
            "record_vs_scan_line_at_110": f"{w}-{l}-{p}",
            "units_at_110_vs_scan": round(u110, 2),
        }
    signed_error = {
        "raw_sim_minus_final": round(mean_signed_vs_close(sim_meds_raw, finals), 3),
        "raw_sim_minus_close": round(mean_signed_vs_close(sim_meds_raw, closes), 3),
        "cal_sim_minus_final": round(mean_signed_vs_close(sim_meds, finals), 3),
        "cal_sim_minus_close": round(mean_signed_vs_close(sim_meds, closes), 3),
    }

    def _by_side(lean_key: str, res_prefix: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for side in ("over", "under"):
            sub = [r for r in per_game if r[lean_key] == side]
            w = sum(1 for r in sub if r[f"{res_prefix}_result_close"] == "W")
            l = sum(1 for r in sub if r[f"{res_prefix}_result_close"] == "L")
            p = sum(1 for r in sub if r[f"{res_prefix}_result_close"] == "P")
            u = sum(float(r[f"{res_prefix}_units_close_110"]) for r in sub)
            out[side] = {"record": f"{w}-{l}-{p}", "units_at_110": round(u, 2)}
        return out

    def _by_bucket(prob_key: str, res_prefix: str) -> dict[str, Any]:
        buckets: dict[str, list] = {}
        for r in per_game:
            b = _prob_bucket(float(r["sim_p_side"]))
            buckets.setdefault(b, []).append(r)
        return {
            b: _summarize_records(v, res_prefix) for b, v in sorted(buckets.items())
        }

    def _by_gap(gap_key: str, res_prefix: str) -> dict[str, Any]:
        buckets: dict[str, list] = {}
        for r in per_game:
            b = _gap_bucket(float(r[gap_key]))
            buckets.setdefault(b, []).append(r)
        return {
            b: _summarize_records(v, res_prefix) for b, v in sorted(buckets.items())
        }

    def _by_week(res_prefix: str) -> dict[str, Any]:
        buckets: dict[str, list] = {}
        for r in per_game:
            buckets.setdefault(str(r["week"]), []).append(r)
        return {
            w: _summarize_records(v, res_prefix) for w, v in sorted(buckets.items(), key=lambda x: int(x[0]))
        }

    old_with_pick = [r for r in per_game if r.get("old_pick")]
    if old_with_pick:
        old_summary = _summarize_records(old_with_pick, "old")
    else:
        old_summary = {
            "record": "38-54-2",
            "units_at_110": -19.5,
            "units_at_close_price": None,
            "note": "from Jason baseline CSV aggregate when per-row pick missing",
        }

    summary = {
        "n_games": len(per_game),
        "mean_signed_error": signed_error,
        "mae": {
            "sim_median_raw": round(_mae(sim_meds_raw, finals), 2),
            "sim_median_calibrated": round(_mae(sim_meds, finals), 2),
            "sim_median": round(_mae(sim_meds, finals), 2),
            "blended": round(_mae(blend_proj, finals), 2),
            "market_close": round(_mae(mkt_lines, finals), 2),
            "old_model_total": round(_mae(old_mod, old_fin), 2) if old_mod else None,
        },
        "sim_only": _summarize_records(per_game, "sim"),
        "blended": _summarize_records(per_game, "blend"),
        "old_model": old_summary,
        "sim_by_side": _by_side("sim_lean", "sim"),
        "blend_by_side": _by_side("blend_lean", "blend"),
        "sim_by_prob_bucket": _by_bucket("sim_p_side", "sim"),
        "sim_by_gap_bucket": _by_gap("sim_gap_pts", "sim"),
        "blend_by_gap_bucket": _by_gap("blend_gap_pts", "blend"),
        "sim_by_week": _by_week("sim"),
        "blend_by_week": _by_week("blend"),
        "card_gate": {
            "n_pass": len(card_rows),
            **_summarize_records(card_rows, "sim"),
            **_card_gate_summary(card_rows),
            "note": (
                "Approximate product gate: sim_p>=50%, EV 4-12% vs scan-time "
                "line (market_total) and pinnacle_price_at_scan when present; "
                "no Phase-4/splits"
            ),
        },
    }
    return per_game, summary


def write_backtest_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
