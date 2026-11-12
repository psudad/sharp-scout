"""Pace-scaled margin standard deviation (shadow / research only).

Live NCAAM still uses ``RULES.margin_sd`` (fixed 10.5). This module provides
√(expected possessions) scaling for shadow EV and calibration backtests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import norm

from sharp_scout.ncaam.rules import RULES

# Reference pace (D-I mean possessions, modern era).
DEFAULT_REF_POSSESSIONS = 67.0
LIVE_MARGIN_SD = RULES.margin_sd


@dataclass(frozen=True)
class SqrtPaceMarginSd:
    """sd(poss) = base * sqrt(expected_poss / ref_poss)."""

    base: float
    ref_poss: float = DEFAULT_REF_POSSESSIONS

    def sd(self, expected_poss: float) -> float:
        poss = max(float(expected_poss), 1.0)
        return float(self.base * math.sqrt(poss / self.ref_poss))


# Fitted on ESPN+consensus spreads, train seasons 2008–2016 (see backtest report).
# Holdout 2017–2021 validates vs fixed LIVE_MARGIN_SD.
# Train 2008–16 SBRO review (Nov 2026): sqrt(poss) base ≈ 10.481 at ref 67.
DEFAULT_PACE_SHADOW = SqrtPaceMarginSd(base=10.481, ref_poss=DEFAULT_REF_POSSESSIONS)
REVIEW_FIT_BASE = 10.481


def margin_sd_sqrt_pace(
    expected_poss: float,
    *,
    base: float | None = None,
    ref_poss: float = DEFAULT_REF_POSSESSIONS,
) -> float:
    """Pace-scaled margin SD used in shadow mode."""
    b = DEFAULT_PACE_SHADOW.base if base is None else float(base)
    return SqrtPaceMarginSd(base=b, ref_poss=ref_poss).sd(expected_poss)


def p_cover_spread_normal(
    margin_mu: float,
    line: float,
    side: str,
    sd: float,
) -> tuple[float, float]:
    """Analytic cover (and push) prob: margin ~ N(margin_mu, sd).

    ``line`` is the offered spread for ``side`` (home line negative when favored).
  """
    sd = max(float(sd), 1e-6)
    mu = float(margin_mu)
    ln = float(line)
    # Home margin M; home covers at home line h if M + h > 0 (half-point lines: no push).
    if side == "home":
        p_win = 1.0 - norm.cdf((-ln - mu) / sd)
        p_push = 0.0
        if abs(ln - round(ln)) < 1e-9:
            p_push = float(norm.cdf((-ln - mu) / sd) - norm.cdf((-ln - 0.5 - mu) / sd))
            p_win = 1.0 - norm.cdf((-ln - 0.5 - mu) / sd)
        return float(min(max(p_win, 0.0), 1.0)), float(max(p_push, 0.0))
    # Away covers at line +L when M < L (dog getting points).
    p_win = norm.cdf((ln - mu) / sd)
    p_push = 0.0
    if abs(ln - round(ln)) < 1e-9:
        p_push = float(norm.cdf((ln + 0.5 - mu) / sd) - norm.cdf((ln - mu) / sd))
        p_win = float(norm.cdf((ln - mu) / sd) - p_push)
    return float(min(max(p_win, 0.0), 1.0)), float(max(p_push, 0.0))


def p_ml_normal(margin_mu: float, side: str, sd: float) -> tuple[float, float]:
    sd = max(float(sd), 1e-6)
    mu = float(margin_mu)
    if side == "home":
        return float(1.0 - norm.cdf(-mu / sd)), 0.0
    return float(norm.cdf(-mu / sd)), 0.0


def log_loss_binary(p: float, y: int) -> float:
    p = min(max(float(p), 1e-6), 1.0 - 1e-6)
    return float(-(y * math.log(p) + (1 - y) * math.log(1.0 - p)))


def cover_nll_per_game(
    margin_mu: float,
    spread_home: float,
    home_covered: int,
    sd: float,
) -> float:
    """NLL for home side covering at closing home spread (ATS calibration)."""
    # Home covers when actual_margin + spread_home > 0; model P uses same line.
    p_home, _ = p_cover_spread_normal(margin_mu, spread_home, "home", sd)
    return log_loss_binary(p_home, home_covered)


def fit_sqrt_pace_base(
    expected_poss: Iterable[float],
    margin_mu: Iterable[float],
    spread_home: Iterable[float],
    home_covered: Iterable[int],
    *,
    ref_poss: float = DEFAULT_REF_POSSESSIONS,
) -> tuple[SqrtPaceMarginSd, float]:
    """Fit ``base`` on training games; returns params and mean train NLL/game."""

    poss = np.asarray(list(expected_poss), dtype=float)
    mu = np.asarray(list(margin_mu), dtype=float)
    spread = np.asarray(list(spread_home), dtype=float)
    y = np.asarray(list(home_covered), dtype=int)

    def objective(base: float) -> float:
        if base <= 0:
            return 1e9
        sd = base * np.sqrt(np.maximum(poss, 1.0) / ref_poss)
        nll = 0.0
        for i in range(len(y)):
            p_h, _ = p_cover_spread_normal(float(mu[i]), float(spread[i]), "home", float(sd[i]))
            nll += log_loss_binary(p_h, int(y[i]))
        return nll / max(len(y), 1)

    res = minimize_scalar(objective, bounds=(8.0, 12.0), method="bounded")
    params = SqrtPaceMarginSd(base=float(res.x), ref_poss=ref_poss)
    return params, float(res.fun)


def constant_sd_nll(
    margin_mu: Iterable[float],
    spread_home: Iterable[float],
    home_covered: Iterable[int],
    sd: float,
) -> float:
    mu = np.asarray(list(margin_mu), dtype=float)
    spread = np.asarray(list(spread_home), dtype=float)
    y = np.asarray(list(home_covered), dtype=int)
    total = 0.0
    for i in range(len(y)):
        total += cover_nll_per_game(float(mu[i]), float(spread[i]), int(y[i]), float(sd))
    return total / max(len(y), 1)
