"""Shin's method to remove the bookmaker margin from a two-way market."""

from __future__ import annotations

import math


def _probs(z: float, q: list[float]) -> list[float]:
    Q = sum(q)
    return [(math.sqrt(z * z + 4.0 * (1.0 - z) * qi * qi / Q) - z) / (2.0 * (1.0 - z)) for qi in q]


def shin_two_way(q1: float, q2: float, *, tol: float = 1e-12) -> tuple[float, float, float]:
    """Vig-free probabilities from implied probabilities q1, q2. Returns (p1, p2, z)."""
    q = [float(q1), float(q2)]
    if sum(q) <= 1.0:
        s = sum(q)
        return q[0] / s, q[1] / s, 0.0
    lo, hi = 0.0, 0.999
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if sum(_probs(mid, q)) > 1.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    z = (lo + hi) / 2.0
    p = _probs(z, q)
    return p[0], p[1], z


def implied(price: float) -> float:
    return abs(price) / (abs(price) + 100.0) if price < 0 else 100.0 / (price + 100.0)
