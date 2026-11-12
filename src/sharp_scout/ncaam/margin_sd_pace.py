"""Pace-scaled margin standard deviation (shadow / research only).

Live NCAAM still uses ``RULES.margin_sd`` (fixed 10.5). Shadow uses modern-era
fits (train 2012–16) with optional pace scaling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Literal

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import norm

from sharp_scout.ncaam.rules import RULES

DEFAULT_REF_POSSESSIONS = 67.0
LIVE_MARGIN_SD = RULES.margin_sd

PaceSdModel = Literal["constant", "sqrt_pace", "linear_pace"]


@dataclass(frozen=True)
class PaceSdParams:
    model: PaceSdModel
    base: float
    ref_poss: float = DEFAULT_REF_POSSESSIONS

    def sd(self, expected_poss: float) -> float:
        return margin_sd_for_model(
            self.model,
            expected_poss,
            base=self.base,
            ref_poss=self.ref_poss,
        )


# Populated by backtest; modern-era sqrt fit target ~11.2 at ref 67 (shadow).
DEFAULT_PACE_SHADOW = PaceSdParams(model="sqrt_pace", base=11.2, ref_poss=DEFAULT_REF_POSSESSIONS)


def margin_sd_for_model(
    model: PaceSdModel | str,
    expected_poss: float,
    *,
    base: float,
    ref_poss: float = DEFAULT_REF_POSSESSIONS,
) -> float:
    poss = max(float(expected_poss), 1.0)
    ref = max(float(ref_poss), 1.0)
    b = float(base)
    if model == "constant":
        return b
    if model == "sqrt_pace":
        return float(b * math.sqrt(poss / ref))
    if model == "linear_pace":
        return float(b * poss / ref)
    raise ValueError(f"unknown pace SD model: {model!r}")


def margin_sd_sqrt_pace(
    expected_poss: float,
    *,
    base: float | None = None,
    ref_poss: float = DEFAULT_REF_POSSESSIONS,
) -> float:
    """Backward-compatible √pace helper for shadow call sites."""
    b = DEFAULT_PACE_SHADOW.base if base is None else float(base)
    return margin_sd_for_model("sqrt_pace", expected_poss, base=b, ref_poss=ref_poss)


def p_cover_spread_normal(
    margin_mu: float,
    line: float,
    side: str,
    sd: float,
) -> tuple[float, float]:
    """Analytic cover (and push) prob: margin ~ N(margin_mu, sd)."""
    sd = max(float(sd), 1e-6)
    mu = float(margin_mu)
    ln = float(line)
    if side == "home":
        p_win = 1.0 - norm.cdf((-ln - mu) / sd)
        p_push = 0.0
        if abs(ln - round(ln)) < 1e-9:
            p_push = float(norm.cdf((-ln - mu) / sd) - norm.cdf((-ln - 0.5 - mu) / sd))
            p_win = 1.0 - norm.cdf((-ln - 0.5 - mu) / sd)
        return float(min(max(p_win, 0.0), 1.0)), float(max(p_push, 0.0))
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
    p_home, _ = p_cover_spread_normal(margin_mu, spread_home, "home", sd)
    return log_loss_binary(p_home, home_covered)


def _nll_for_model(
    model: PaceSdModel,
    base: float,
    poss: np.ndarray,
    mu: np.ndarray,
    spread: np.ndarray,
    y: np.ndarray,
    *,
    ref_poss: float,
) -> float:
    nll = 0.0
    for i in range(len(y)):
        sd = margin_sd_for_model(model, float(poss[i]), base=base, ref_poss=ref_poss)
        nll += cover_nll_per_game(float(mu[i]), float(spread[i]), int(y[i]), sd)
    return nll / max(len(y), 1)


def fit_pace_sd_base(
    model: PaceSdModel,
    expected_poss: Iterable[float],
    margin_mu: Iterable[float],
    spread_home: Iterable[float],
    home_covered: Iterable[int],
    *,
    ref_poss: float = DEFAULT_REF_POSSESSIONS,
    base_bounds: tuple[float, float] = (9.0, 14.0),
) -> tuple[PaceSdParams, float]:
    """Fit ``base`` for the given pace model on training games."""

    poss = np.asarray(list(expected_poss), dtype=float)
    mu = np.asarray(list(margin_mu), dtype=float)
    spread = np.asarray(list(spread_home), dtype=float)
    y = np.asarray(list(home_covered), dtype=int)

    def objective(base: float) -> float:
        if base <= 0:
            return 1e9
        return _nll_for_model(model, base, poss, mu, spread, y, ref_poss=ref_poss)

    res = minimize_scalar(objective, bounds=base_bounds, method="bounded")
    params = PaceSdParams(model=model, base=float(res.x), ref_poss=ref_poss)
    return params, float(res.fun)


def fit_sqrt_pace_base(
    expected_poss: Iterable[float],
    margin_mu: Iterable[float],
    spread_home: Iterable[float],
    home_covered: Iterable[int],
    *,
    ref_poss: float = DEFAULT_REF_POSSESSIONS,
) -> tuple[PaceSdParams, float]:
    return fit_pace_sd_base(
        "sqrt_pace",
        expected_poss,
        margin_mu,
        spread_home,
        home_covered,
        ref_poss=ref_poss,
    )


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
