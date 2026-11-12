"""NCAAM price-edge gate — EV vs Pinnacle no-vig fair before model tilt (shadow by default)."""

from __future__ import annotations

import math
from typing import Any

from sharp_scout.ncaam.rules import RULES
from sharp_scout.utils.odds import expected_value, expected_value_with_push, win_prob_to_conditional


def _decimal_odds(american: float) -> float:
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def price_edge_ev(
    p_fair: float | None,
    price: float | None,
    p_push: float = 0.0,
) -> float | None:
    """EV of the offered price vs Pinnacle no-vig fair only (no model tilt).

    Returns None when ``p_fair`` is missing — never invent a fair price.
    Whole-number spread hooks use push-aware EV; ML and integer lines use p_push=0.
    """
    if p_fair is None or price is None:
        return None
    pf = float(p_fair)
    pp = max(0.0, float(p_push))
    if pp > 0:
        p_cond = win_prob_to_conditional(pf, pp)
        return expected_value_with_push(p_cond, float(price), pp)
    return expected_value(pf, float(price))


def price_edge_qualifies(
    p_fair: float | None,
    price: float | None,
    *,
    min_edge: float = 0.01,
    p_push: float = 0.0,
) -> bool:
    ev = price_edge_ev(p_fair, price, p_push)
    if ev is None:
        return False
    return ev >= min_edge


def split_lock_ev_parts(
    p_fair: float | None,
    p_true: float | None,
    price: float | None,
) -> tuple[float | None, float | None]:
    """Decompose lock EV like the Nov 11 review: price part + model tilt part.

    Uses the report's lock-time formulas (no push term):
    price_part = p_fair × dec − 1
    model_part = (p_true − p_fair) × dec
  """
    if p_fair is None or p_true is None or price is None:
        return None, None
    dec = _decimal_odds(float(price))
    price_part = float(p_fair) * dec - 1.0
    model_part = (float(p_true) - float(p_fair)) * dec
    return price_part, model_part


def diagnostic_row(play: dict[str, Any], *, min_edge: float = 0.01) -> dict[str, Any]:
    """Shadow diagnostics for one board candidate (not written to the official ledger)."""
    p_fair = play.get("p_fair")
    p_true = play.get("p_true")
    price = play.get("price")
    p_push = float(play.get("p_push") or 0.0)
    edge = price_edge_ev(p_fair, price, p_push)
    price_part, model_part = split_lock_ev_parts(p_fair, p_true, price)
    return {
        "espn_id": play.get("espn_id"),
        "event_id": play.get("event_id"),
        "market": play.get("market"),
        "side": play.get("side"),
        "line": play.get("line"),
        "price": price,
        "book": play.get("book"),
        "p_fair": p_fair,
        "p_true": p_true,
        "p_push": p_push,
        "price_edge": round(edge, 6) if edge is not None else None,
        "price_part": round(price_part, 6) if price_part is not None else None,
        "model_part": round(model_part, 6) if model_part is not None else None,
        "min_edge": min_edge,
        "would_pass_gate": price_edge_qualifies(p_fair, price, min_edge=min_edge, p_push=p_push),
        "et_day": play.get("et_day"),
        "ev_at_lock": play.get("ev"),
    }


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = wins / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (max(0.0, center - margin), min(1.0, center + margin))
