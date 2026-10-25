"""Walk-forward bias + blend weight for live NFL totals (matches season backtest)."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sharp_scout.config import ROOT, get_settings
from sharp_scout.nfl.totals.blend import choose_blend_weight
from sharp_scout.nfl.totals.calibrate import walk_forward_total_bias
from sharp_scout.nfl.totals.tracker import load_totals_board

logger = logging.getLogger(__name__)

DEFAULT_TRAINING_CSV = ROOT / "reports" / "nfl_totals_sim_backtest_2026.csv"


@dataclass
class LiveTotalsCalibration:
    bias: float
    blend_weight_sim: float
    n_training_games: int
    source: str


def _parse_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _rows_from_backtest_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            wk = row.get("week")
            ft = _parse_float(row.get("final_total"))
            raw = _parse_float(row.get("sim_median_raw")) or _parse_float(row.get("sim_median"))
            mkt = _parse_float(row.get("pinnacle_close_line")) or _parse_float(row.get("scan_line"))
            if wk is None or ft is None or raw is None or mkt is None:
                continue
            out.append(
                {
                    "week": int(wk),
                    "sim_median_raw": raw,
                    "final_total": ft,
                    "market_line": mkt,
                }
            )
    return out


def _rows_from_settled_board() -> list[dict[str, Any]]:
    board = load_totals_board()
    out: list[dict[str, Any]] = []
    for g in board.get("games") or []:
        if g.get("status") != "settled" and g.get("graded_at") is None:
            hs, as_ = g.get("home_score"), g.get("away_score")
            if hs is None or as_ is None:
                continue
        else:
            hs, as_ = g.get("home_score"), g.get("away_score")
            if hs is None or as_ is None:
                continue
        raw = _parse_float(g.get("sim_median_raw")) or _parse_float(g.get("sim_median"))
        mkt = _parse_float(g.get("market_line"))
        wk = g.get("week")
        if raw is None or mkt is None or wk is None:
            continue
        out.append(
            {
                "week": int(wk),
                "sim_median_raw": raw,
                "final_total": float(as_) + float(hs),
                "market_line": mkt,
            }
        )
    return out


def _merge_training_rows(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by week+final+market (approximate); prefer later sources."""
    seen: set[tuple[int, float, float]] = set()
    merged: list[dict[str, Any]] = []
    for rows in sources:
        for r in rows:
            key = (int(r["week"]), round(float(r["final_total"]), 1), round(float(r["market_line"]), 1))
            if key in seen:
                continue
            seen.add(key)
            merged.append(r)
    merged.sort(key=lambda x: (x["week"], x["final_total"]))
    return merged


def resolve_live_calibration(
    *,
    before_week: int | None = None,
    training_csv: Path | None = None,
    min_bias_history: int = 10,
    min_blend_history: int = 12,
) -> LiveTotalsCalibration:
    """OOS calibration for the current slate (prior weeks only)."""
    settings = get_settings()
    csv_path = training_csv or Path(
        getattr(settings, "nfl_totals_calibration_csv", "") or DEFAULT_TRAINING_CSV
    )
    if not csv_path.is_absolute():
        csv_path = ROOT / csv_path

    all_rows = _merge_training_rows(_rows_from_backtest_csv(csv_path), _rows_from_settled_board())
    if before_week is not None:
        train = [r for r in all_rows if int(r["week"]) < int(before_week)]
    else:
        train = all_rows

    sim_raw = [float(r["sim_median_raw"]) for r in train]
    finals = [float(r["final_total"]) for r in train]
    markets = [float(r["market_line"]) for r in train]

    bias = walk_forward_total_bias(sim_raw, finals, min_history=min_bias_history)
    cal = [s - bias for s in sim_raw]

    w_auto = 0.0
    if len(train) >= min_blend_history:
        w_auto, _, _, _ = choose_blend_weight(cal, markets, finals)

    fixed = float(settings.nfl_totals_blend_weight_sim)
    blend_auto = bool(getattr(settings, "nfl_totals_blend_auto", True))
    if fixed > 0.0:
        w_sim = fixed
        source = "settings.nfl_totals_blend_weight_sim"
    elif blend_auto and len(train) >= min_blend_history:
        w_sim = w_auto
        source = "walk_forward_choose_blend_weight"
    else:
        w_sim = 0.0
        source = "market_only_insufficient_history"

    return LiveTotalsCalibration(
        bias=bias,
        blend_weight_sim=w_sim,
        n_training_games=len(train),
        source=source,
    )


def infer_slate_week(events: list[dict[str, Any]]) -> int | None:
    weeks = [ev.get("week") for ev in events if ev.get("week") is not None]
    if weeks:
        return int(max(int(w) for w in weeks))
    return None


def lean_from_probabilities(p_over: float | None, p_under: float | None) -> str | None:
    if p_over is None or p_under is None:
        return None
    if p_over >= p_under:
        return "over"
    return "under"
