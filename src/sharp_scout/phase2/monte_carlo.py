"""Phase 2 — Monte Carlo score simulation → P_true cover / win probabilities."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from sharp_scout.config import get_settings

logger = logging.getLogger(__name__)

# Common spread keys to price
DEFAULT_SPREAD_KEYS = [-7.5, -7.0, -3.5, -3.0, -2.5, -1.5, -1.0, 0.0, 1.0, 1.5, 2.5, 3.0, 3.5, 7.0, 7.5]
DEFAULT_TOTAL_KEYS = [37.5, 40.5, 41.5, 42.5, 43.5, 44.5, 45.5, 46.5, 47.5, 48.5, 49.5, 50.5, 51.5, 52.5, 55.5]


@dataclass
class GameSimResult:
    home_team: str
    away_team: str
    mu_home: float
    mu_away: float
    n_sims: int
    model_spread: float  # away - home (home favored negative)
    model_total: float
    p_home_win: float
    p_away_win: float
    p_push_ml: float
    cover_probs: dict[float, float] = field(default_factory=dict)  # P(home covers home_line)
    over_probs: dict[float, float] = field(default_factory=dict)
    home_scores: np.ndarray | None = field(default=None, repr=False)
    away_scores: np.ndarray | None = field(default=None, repr=False)


def score_noise_params(
    mu_home: float,
    mu_away: float,
    margin_sd: float,
    total_sd: float,
) -> tuple[float, float, float]:
    """Per-team score sd / correlation that reproduce the target margin and total sd.

    var(margin) = s_h² + s_a² − 2ρ s_h s_a ;  var(total) = s_h² + s_a² + 2ρ s_h s_a
    → s_h² + s_a² = (var_m + var_t)/2 ;  ρ s_h s_a = (var_t − var_m)/4.
    Team sds split in proportion to their means (bigger offenses are noisier).
    """
    var_m, var_t = margin_sd**2, total_sd**2
    sum_sq = (var_m + var_t) / 2.0
    w = np.array([max(mu_home, 1.0), max(mu_away, 1.0)], dtype=float)
    w = w / np.sqrt((w**2).sum())
    s_h, s_a = float(np.sqrt(sum_sq) * w[0]), float(np.sqrt(sum_sq) * w[1])
    rho = float(np.clip((var_t - var_m) / (4.0 * s_h * s_a), -0.6, 0.6))
    return s_h, s_a, rho


def _sample_scores(
    mu_home: float,
    mu_away: float,
    n: int,
    rho: float | None = None,
    rng: np.random.Generator | None = None,
    *,
    margin_sd: float | None = None,
    total_sd: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Correlated non-negative scores via latent bivariate normal → gamma quantiles.

    Per-team noise is calibrated to the sport's realized margin/total sd (see
    ``score_noise_params``). The old fixed CV=0.28 implied a margin sd of ~8 for NFL and
    ~10 for CFB versus ~13.5 / ~17 in reality, so every cover probability was
    overconfident — a 4-point model edge showed as 69% instead of ~61%.
    """
    rng = rng or np.random.default_rng()
    if margin_sd is not None and total_sd is not None:
        s_h, s_a, rho_cal = score_noise_params(mu_home, mu_away, margin_sd, total_sd)
        rho = rho_cal if rho is None else rho
    else:
        cv = 0.28
        s_h, s_a = cv * mu_home, cv * mu_away
        rho = 0.15 if rho is None else rho
    mean = np.array([0.0, 0.0])
    cov = np.array([[1.0, rho], [rho, 1.0]])
    z = rng.multivariate_normal(mean, cov, size=n)
    # Gamma with mean mu and sd s: shape = (mu/s)², scale = s²/mu
    shape_h = (mu_home / s_h) ** 2
    scale_h = s_h**2 / mu_home
    shape_a = (mu_away / s_a) ** 2
    scale_a = s_a**2 / mu_away
    u_h = stats.norm.cdf(z[:, 0])
    u_a = stats.norm.cdf(z[:, 1])
    # Clip to avoid 0/1
    u_h = np.clip(u_h, 1e-6, 1 - 1e-6)
    u_a = np.clip(u_a, 1e-6, 1 - 1e-6)
    home = stats.gamma.ppf(u_h, a=shape_h, scale=scale_h)
    away = stats.gamma.ppf(u_a, a=shape_a, scale=scale_a)
    # Discretize to football scores (approx multiples of FG/TD noise)
    home_i = np.rint(home).astype(int)
    away_i = np.rint(away).astype(int)
    return np.maximum(home_i, 0), np.maximum(away_i, 0)


def simulate_game(
    home_team: str,
    away_team: str,
    mu_home: float,
    mu_away: float,
    n_sims: int | None = None,
    spread_keys: list[float] | None = None,
    total_keys: list[float] | None = None,
    seed: int | None = 42,
    sport: str | None = None,
) -> GameSimResult:
    settings = get_settings()
    n = n_sims or settings.monte_carlo_sims
    rng = np.random.default_rng(seed)
    if sport:
        from sharp_scout.sports import get_sport

        cfg = get_sport(sport)
        home_s, away_s = _sample_scores(
            mu_home, mu_away, n, rng=rng, margin_sd=cfg.margin_sd, total_sd=cfg.total_sd
        )
    else:
        home_s, away_s = _sample_scores(mu_home, mu_away, n, rng=rng)

    margin = home_s - away_s  # >0 home wins
    total = home_s + away_s

    p_home = float(np.mean(margin > 0))
    p_away = float(np.mean(margin < 0))
    p_tie = float(np.mean(margin == 0))

    spread_keys = spread_keys if spread_keys is not None else DEFAULT_SPREAD_KEYS
    total_keys = total_keys if total_keys is not None else DEFAULT_TOTAL_KEYS

    # home_line is the spread on the home team (e.g. -3 means home favored by 3)
    cover: dict[float, float] = {}
    for line in spread_keys:
        # Home covers if home_score + line > away_score  (line negative when home favored)
        cover[float(line)] = float(np.mean((home_s + line) > away_s))

    overs: dict[float, float] = {}
    for tline in total_keys:
        overs[float(tline)] = float(np.mean(total > tline))

    model_spread = float(mu_away - mu_home)
    model_total = float(mu_home + mu_away)

    return GameSimResult(
        home_team=home_team,
        away_team=away_team,
        mu_home=mu_home,
        mu_away=mu_away,
        n_sims=n,
        model_spread=model_spread,
        model_total=model_total,
        p_home_win=p_home,
        p_away_win=p_away,
        p_push_ml=p_tie,
        cover_probs=cover,
        over_probs=overs,
        home_scores=home_s,
        away_scores=away_s,
    )


def p_true_for_market(
    sim: GameSimResult,
    market: str,
    side: str,
    line: float | None,
) -> float:
    """Look up / interpolate P_true for a specific offered line."""
    if market == "h2h":
        if side == "home":
            return sim.p_home_win + 0.5 * sim.p_push_ml
        return sim.p_away_win + 0.5 * sim.p_push_ml

    if market == "spreads":
        if line is None:
            raise ValueError("spread requires line")
        # cover_probs keyed by home line
        home_line = float(line) if side == "home" else -float(line)
        # If side is away with away_line=-2.5, home_line=+2.5
        if side == "away":
            home_line = -float(line)
        p_home_cover = _interp_prob(sim.cover_probs, home_line)
        return p_home_cover if side == "home" else 1.0 - p_home_cover

    if market == "totals":
        if line is None:
            raise ValueError("total requires line")
        p_over = _interp_prob(sim.over_probs, float(line))
        return p_over if side == "over" else 1.0 - p_over

    raise ValueError(f"Unknown market {market}")


def _interp_prob(grid: dict[float, float], x: float) -> float:
    if not grid:
        return 0.5
    if x in grid:
        return grid[x]
    keys = sorted(grid.keys())
    if x <= keys[0]:
        return grid[keys[0]]
    if x >= keys[-1]:
        return grid[keys[-1]]
    for i in range(len(keys) - 1):
        a, b = keys[i], keys[i + 1]
        if a <= x <= b:
            t = (x - a) / (b - a) if b != a else 0.0
            return grid[a] * (1 - t) + grid[b] * t
    return 0.5