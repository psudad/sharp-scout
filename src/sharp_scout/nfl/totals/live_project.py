"""Apply walk-forward calibration to a single simulation result."""

from __future__ import annotations

from typing import Any

import numpy as np

from sharp_scout.nfl.totals.simulate import TotalsSimResult, sim_result_to_dict


def apply_live_calibration(
    sim: TotalsSimResult,
    *,
    bias: float,
    blend_weight_sim: float,
    market_line: float | None,
) -> dict[str, Any]:
    """Calibrated medians, probabilities vs market, blend, and consistent lean."""
    sim_median_raw = float(sim.sim_median)
    sim_mean_raw = float(sim.sim_mean)
    bias_f = float(bias)

    sim_median_cal = sim_median_raw - bias_f
    sim_mean_cal = sim_mean_raw - bias_f

    p_over = p_under = p_push = None
    if market_line is not None and sim.total_samples is not None:
        totals = np.asarray(sim.total_samples, dtype=float) - bias_f
        line = float(market_line)
        p_over = float(np.mean(totals > line))
        p_under = float(np.mean(totals < line))
        p_push = float(np.mean(totals == line))
    elif market_line is not None:
        p_over, p_under, p_push = sim.p_over, sim.p_under, sim.p_push

    from sharp_scout.nfl.totals.blend import blend_total
    from sharp_scout.nfl.totals.live_calibration import lean_from_probabilities

    blended = (
        blend_total(sim_median_cal, market_line, weight_sim=blend_weight_sim)
        if market_line is not None
        else sim_median_cal
    )
    lean = lean_from_probabilities(p_over, p_under)
    if lean is None:
        lean = "over" if sim_median_cal >= (market_line or sim_median_cal) else "under"

    out = sim_result_to_dict(sim, blended=blended)
    out["sim_median_raw"] = round(sim_median_raw, 2)
    out["sim_mean_raw"] = round(sim_mean_raw, 2)
    out["sim_median"] = round(sim_median_cal, 2)
    out["sim_mean"] = round(sim_mean_cal, 2)
    out["sim_lean"] = lean
    out["walk_forward_bias"] = round(bias_f, 3)
    out["blend_weight_sim"] = round(float(blend_weight_sim), 3)
    if p_over is not None:
        out["p_over"] = round(p_over, 4)
        out["p_under"] = round(p_under or 0.0, 4)
        out["p_push"] = round(p_push or 0.0, 4)
    out["blended_total"] = round(blended, 2)
    out["projection_total"] = round(blended, 2)
    return out
