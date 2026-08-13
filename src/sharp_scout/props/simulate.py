"""Phase 2 — Non-normal Monte Carlo for player props."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy import stats

from sharp_scout.config import get_settings
from sharp_scout.props.usage import PlayerUsage

PropKind = Literal[
    "player_receptions",
    "player_reception_yds",
    "player_reception_tds",
    "player_rush_yds",
    "player_rush_attempts",
    "player_rush_tds",
    "player_pass_yds",
    "player_pass_tds",
    "player_pass_attempts",
    "player_anytime_td",
]


@dataclass
class PropSimResult:
    player_name: str
    team: str
    market: str
    mean: float
    median: float
    samples: np.ndarray = field(repr=False)
    n_sims: int = 0

    def p_over(self, line: float) -> float:
        return float(np.mean(self.samples > line))

    def p_under(self, line: float) -> float:
        return float(np.mean(self.samples < line))

    def p_push(self, line: float) -> float:
        return float(np.mean(np.isclose(self.samples, line, atol=1e-9)))


def _negbin_samples(mu: float, n: int, dispersion: float = 1.4, rng: np.random.Generator | None = None) -> np.ndarray:
    """Negative binomial with mean mu; dispersion>1 → over-dispersed vs Poisson."""
    rng = rng or np.random.default_rng()
    mu = max(mu, 1e-6)
    # scipy nbinom: mean = n * (1-p) / p  → set n = mu / (d-1), p = 1/d
    d = max(dispersion, 1.05)
    n_param = mu / (d - 1)
    p = 1.0 / d
    return stats.nbinom.rvs(n_param, p, size=n, random_state=rng)


def _gamma_samples(mu: float, n: int, cv: float = 0.55, rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng()
    mu = max(mu, 1e-6)
    shape = 1.0 / (cv**2)
    scale = mu / shape
    return np.maximum(stats.gamma.rvs(a=shape, scale=scale, size=n, random_state=rng), 0.0)


def simulate_prop(
    usage: PlayerUsage,
    market: str,
    n_sims: int | None = None,
    seed: int | None = 42,
) -> PropSimResult:
    settings = get_settings()
    n = n_sims or settings.monte_carlo_sims
    rng = np.random.default_rng(seed)
    market = market.strip()

    if market == "player_receptions":
        lam = max(usage.exp_receptions, 0.1)
        samples = _negbin_samples(lam, n, dispersion=1.35, rng=rng).astype(float)
    elif market == "player_reception_yds":
        samples = _gamma_samples(max(usage.exp_rec_yards, 1.0), n, cv=0.60, rng=rng)
    elif market == "player_reception_tds":
        samples = _negbin_samples(max(usage.exp_rec_tds, 0.05), n, dispersion=1.6, rng=rng).astype(float)
    elif market == "player_rush_yds":
        samples = _gamma_samples(max(usage.exp_rush_yards, 1.0), n, cv=0.58, rng=rng)
    elif market == "player_rush_attempts":
        samples = _negbin_samples(max(usage.exp_rush_att, 0.5), n, dispersion=1.3, rng=rng).astype(float)
    elif market == "player_rush_tds":
        samples = _negbin_samples(max(usage.exp_rush_tds, 0.05), n, dispersion=1.6, rng=rng).astype(float)
    elif market == "player_pass_yds":
        samples = _gamma_samples(max(usage.exp_pass_yards, 1.0), n, cv=0.42, rng=rng)
    elif market == "player_pass_tds":
        samples = _negbin_samples(max(usage.exp_pass_tds, 0.1), n, dispersion=1.45, rng=rng).astype(float)
    elif market == "player_pass_attempts":
        samples = _negbin_samples(max(usage.exp_pass_att, 1.0), n, dispersion=1.25, rng=rng).astype(float)
    elif market == "player_anytime_td":
        # Bernoulli from combined TD rate
        p = 1.0 - np.exp(-(usage.exp_rec_tds + usage.exp_rush_tds + 0.15 * usage.exp_pass_tds))
        p = float(np.clip(p, 0.02, 0.85))
        samples = rng.random(n) < p
        samples = samples.astype(float)
    else:
        raise ValueError(f"Unsupported prop market: {market}")

    return PropSimResult(
        player_name=usage.player_name,
        team=usage.team,
        market=market,
        mean=float(np.mean(samples)),
        median=float(np.median(samples)),
        samples=samples,
        n_sims=n,
    )


def p_true_over_under(sim: PropSimResult, side: str, line: float) -> float:
    if side.lower() == "over":
        # pushes: half credit optional — use strict over for O/U props
        return sim.p_over(line) + 0.5 * sim.p_push(line)
    return sim.p_under(line) + 0.5 * sim.p_push(line)


CORE_PROP_MARKETS = [
    "player_pass_yds",
    "player_pass_tds",
    "player_rush_yds",
    "player_receptions",
    "player_reception_yds",
    "player_reception_tds",
    "player_anytime_td",
]