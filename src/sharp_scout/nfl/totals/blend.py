"""Shrink simulation toward the market total."""

from __future__ import annotations

import numpy as np


def blend_total(sim_median: float, market_line: float, *, weight_sim: float) -> float:
    w = float(np.clip(weight_sim, 0.0, 1.0))
    return w * float(sim_median) + (1.0 - w) * float(market_line)


def choose_blend_weight(
    sim_projections: list[float],
    market_lines: list[float],
    finals: list[float],
    *,
    step: float = 0.05,
) -> tuple[float, float, float, float]:
    """Pick w so blended MAE is no worse than market-only MAE on the sample.

    Returns (best_w, sim_mae, blended_mae, market_mae).
    """
    if not sim_projections or len(sim_projections) != len(market_lines) == len(finals):
        return 0.0, 0.0, 0.0, 0.0

    sim = np.array(sim_projections, dtype=float)
    mkt = np.array(market_lines, dtype=float)
    fin = np.array(finals, dtype=float)
    market_mae = float(np.mean(np.abs(mkt - fin)))

    best_w = 0.0
    best_mae = market_mae
    for w in np.arange(0.0, 1.0001, step):
        blended = w * sim + (1.0 - w) * mkt
        mae = float(np.mean(np.abs(blended - fin)))
        if mae <= market_mae + 1e-9 and mae <= best_mae + 1e-9:
            best_w = float(w)
            best_mae = mae

    sim_mae = float(np.mean(np.abs(sim - fin)))
    if best_w == 0.0:
        best_mae = market_mae
    return best_w, sim_mae, best_mae, market_mae
