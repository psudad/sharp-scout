"""Walk-forward bias correction for simulation totals (no full-season fit)."""

from __future__ import annotations


def walk_forward_total_bias(
    hist_sim_median: list[float],
    hist_final: list[float],
    *,
    min_history: int = 10,
) -> float:
    """Mean signed error (sim median − final) on prior games only.

    Apply as ``sim_calibrated = sim_median - bias`` so low sim bias (negative mean)
    shifts projections up.
    """
    if len(hist_sim_median) < min_history:
        return 0.0
    n = len(hist_sim_median)
    return float(sum(s - f for s, f in zip(hist_sim_median, hist_final, strict=True)) / n)


def mean_signed_vs_close(
    sim_values: list[float], close_lines: list[float]
) -> float:
    if not sim_values:
        return 0.0
    return float(
        sum(s - c for s, c in zip(sim_values, close_lines, strict=True)) / len(sim_values)
    )
