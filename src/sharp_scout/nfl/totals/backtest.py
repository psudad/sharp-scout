"""Walk-forward backtest for NFL totals sim + market blend (Weeks 1–6)."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from sharp_scout.data.nflfastr import load_pbp, nfl_rating_plays
from sharp_scout.nfl.totals.blend import blend_total, choose_blend_weight
from sharp_scout.nfl.totals.rates import build_team_drive_rates
from sharp_scout.nfl.totals.simulate import simulate_nfl_total
from sharp_scout.phase3.market import sharp_consensus
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)


def _pbp_before_week(pbp: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    if pbp.empty:
        return pbp
    s = pd.to_numeric(pbp["season"], errors="coerce")
    w = pd.to_numeric(pbp["week"], errors="coerce")
    mask = (s < season) | ((s == season) & (w < week))
    return pbp[mask].copy()


def backtest_from_csv(
    csv_path: Path,
    *,
    max_week: int = 6,
    pbp: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Run out-of-sample sim on rows through ``max_week`` using prior-week PBP only."""
    rows: list[dict[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if pbp is None:
        pbp = load_pbp([2025, 2026])

    sim_medians: list[float] = []
    markets: list[float] = []
    finals: list[float] = []
    lean_w = lean_l = lean_p = 0

    for row in rows:
        try:
            week = int(row.get("week") or 0)
        except ValueError:
            continue
        if week > max_week:
            continue
        final_total = float(row.get("final_total") or 0)
        market = float(row.get("market_total") or row.get("pinnacle_close_line") or 0)
        if market <= 0:
            continue

        away = normalize_team(row.get("away") or "", "nfl") or row.get("away", "")
        home = normalize_team(row.get("home") or "", "nfl") or row.get("home", "")
        season = 2026

        hist = _pbp_before_week(pbp, season, week)
        if hist.empty:
            hist = nfl_rating_plays(pbp)
        rates = build_team_drive_rates(hist)
        hr = rates.get(home) or rates.get(normalize_team(home, "nfl") or "")
        ar = rates.get(away) or rates.get(normalize_team(away, "nfl") or "")
        if not hr or not ar:
            from sharp_scout.nfl.totals.rates import team_rates

            hr = team_rates(rates, home)
            ar = team_rates(rates, away)

        sim = simulate_nfl_total(
            home_team=home,
            away_team=away,
            home_rates=hr,
            away_rates=ar,
            market_line=market,
            n_sims=4000,
            seed=week * 1000 + hash(f"{away}@{home}") % 1000,
        )
        sim_medians.append(sim.sim_median)
        markets.append(market)
        finals.append(final_total)

    w, sim_mae, blend_mae, mkt_mae = choose_blend_weight(sim_medians, markets, finals)

    for sim_m, mkt, fin in zip(sim_medians, markets, finals, strict=True):
        blended = blend_total(sim_m, mkt, weight_sim=w)
        line = mkt
        lean = "over" if blended >= line else "under"
        if fin > line:
            res = "W" if lean == "over" else "L"
        elif fin < line:
            res = "W" if lean == "under" else "L"
        else:
            res = "P"
        if res == "W":
            lean_w += 1
        elif res == "L":
            lean_l += 1
        else:
            lean_p += 1

    return {
        "games": len(sim_medians),
        "blend_weight_sim": round(w, 2),
        "sim_mae": round(sim_mae, 2),
        "blended_mae": round(blend_mae, 2),
        "market_mae": round(mkt_mae, 2),
        "blended_lean_record": f"{lean_w}-{lean_l}-{lean_p}",
    }


def market_line_from_event(event: dict[str, Any]) -> float | None:
    sharp = sharp_consensus(event, "totals")
    if sharp:
        line = sharp.get("line")
        if line is not None:
            return float(line)
        for o in sharp.get("outcomes") or []:
            if o.get("point") is not None:
                return float(o["point"])
    for bm in (event.get("bookmakers") or {}).values():
        for o in (bm.get("markets") or {}).get("totals") or []:
            if o.get("point") is not None:
                return float(o["point"])
    return None
