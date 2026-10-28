"""Shrink model projections toward the market (reduces over-disagreement)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BlendParams:
    market_blend_margin: float
    market_blend_total: float
    max_edge_spread: float | None = None
    max_edge_total: float | None = None


def market_implied_margin(spread_home: float) -> float:
    """Closing home spread (negative = home favored) → consensus home margin."""
    return -float(spread_home)


def _cap_signed_edge(edge: float, cap: float | None) -> float:
    if cap is None:
        return edge
    cap = float(cap)
    if abs(edge) <= cap:
        return edge
    return cap if edge > 0 else -cap


def blend_margin(margin: float, spread_home: float, params: BlendParams) -> float:
    mkt = market_implied_margin(spread_home)
    w = params.market_blend_margin
    blended = (1.0 - w) * margin + w * mkt
    edge = blended + float(spread_home)
    edge = _cap_signed_edge(edge, params.max_edge_spread)
    return edge - float(spread_home)


def blend_total(total: float, total_line: float, params: BlendParams) -> float:
    w = params.market_blend_total
    blended = (1.0 - w) * total + w * float(total_line)
    edge = blended - float(total_line)
    edge = _cap_signed_edge(edge, params.max_edge_total)
    return float(total_line) + edge


def blend_projection(
    proj: dict[str, float],
    *,
    spread_home: float | None,
    total_line: float | None,
    params: BlendParams,
) -> dict[str, float]:
    margin = float(proj["margin"])
    total = float(proj["total"])
    if spread_home is not None:
        margin = blend_margin(margin, float(spread_home), params)
    if total_line is not None:
        total = blend_total(total, float(total_line), params)
    home_pts = (total + margin) / 2.0
    away_pts = (total - margin) / 2.0
    return {**proj, "margin": margin, "total": total, "home_pts": home_pts, "away_pts": away_pts}
