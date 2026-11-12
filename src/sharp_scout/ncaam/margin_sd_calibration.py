"""Calibration metrics for margin-SD backtests (research)."""

from __future__ import annotations

from typing import Any

from sharp_scout.analysis.calibration import brier_score, reliability_bins


def reliability_table(pairs: list[tuple[float, int]], n_bins: int = 10) -> list[dict[str, Any]]:
    return reliability_bins(pairs, n_bins=n_bins)


def summarize_calibration(
    pairs: list[tuple[float, int]],
    *,
    label: str,
) -> dict[str, Any]:
    n = len(pairs)
    brier = brier_score(pairs)
    mean_p = round(sum(p for p, _ in pairs) / n, 4) if n else None
    obs = round(sum(y for _, y in pairs) / n, 4) if n else None
    return {
        "label": label,
        "n": n,
        "log_loss": round(mean_log_loss(pairs), 4) if n else None,
        "brier": brier,
        "pred_mean": mean_p,
        "obs_freq": obs,
        "bins": reliability_table(pairs),
    }


def mean_log_loss(pairs: list[tuple[float, int]]) -> float | None:
    from sharp_scout.ncaam.margin_sd_pace import log_loss_binary

    if not pairs:
        return None
    return sum(log_loss_binary(p, y) for p, y in pairs) / len(pairs)
