"""Normalize closing lines to home spread (negative = home favored) and totals."""

from __future__ import annotations

import math


def nflverse_home_spread(spread_line: float | None) -> float | None:
    """nflverse ``spread_line`` is positive when home is favored; flip to betting home spread."""
    if spread_line is None or (isinstance(spread_line, float) and math.isnan(spread_line)):
        return None
    return -float(spread_line)


def cfb_pbp_home_spread(spread: float | None) -> float | None:
    """cfbfastR ``spread`` on PBP is already home spread (negative = home favored)."""
    if spread is None or (isinstance(spread, float) and math.isnan(spread)):
        return None
    return float(spread)


def grade_ats(
    actual_margin: float,
    spread_home: float,
    *,
    proj_margin: float,
    min_edge: float,
) -> str | None:
    """Return win/loss/push or None if edge below threshold."""
    edge = proj_margin + float(spread_home)
    if abs(edge) < min_edge:
        return None
    pick_home = edge > 0
    adj = actual_margin + float(spread_home)
    if adj == 0:
        return "push"
    result_home = adj > 0
    return "win" if pick_home == result_home else "loss"


def grade_total(
    actual_total: float,
    close_total: float,
    *,
    proj_total: float,
    min_edge: float,
) -> str | None:
    edge = proj_total - float(close_total)
    if abs(edge) < min_edge:
        return None
    pick_over = edge > 0
    if actual_total == float(close_total):
        return "push"
    result_over = actual_total > float(close_total)
    return "win" if pick_over == result_over else "loss"


def roi_at_110(wins: int, losses: int) -> float | None:
    n = wins + losses
    if n == 0:
        return None
    units = wins * (100.0 / 110.0) - losses
    return round(units / n * 100.0, 2)


def edge_bucket_label(edge_abs: float, buckets: tuple[tuple[float, float | None], ...]) -> str:
    for lo, hi in buckets:
        if hi is None and edge_abs >= lo:
            return f"{lo:g}+"
        if hi is not None and lo <= edge_abs < hi:
            return f"{lo:g}-{hi:g}"
    return "below_3"
