"""Possession / drive-based NFL total simulation."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sharp_scout.nfl.totals.rates import TeamDriveRates, team_rates


@dataclass
class TotalsSimResult:
    home_team: str
    away_team: str
    n_sims: int
    sim_mean: float
    sim_median: float
    sim_std: float
    market_line: float | None
    p_over: float | None = None
    p_under: float | None = None
    p_push: float | None = None
    sim_lean: str | None = None
    total_samples: np.ndarray | None = field(default=None, repr=False)


def _game_script_pace_adj(home_spread: float | None) -> tuple[float, float]:
    """Spread (home perspective, neg = home favored) → pace multipliers (home, away)."""
    if home_spread is None:
        return 1.0, 1.0
    fav_margin = -float(home_spread)
    if fav_margin >= 10:
        return 0.94, 1.06
    if fav_margin >= 7:
        return 0.96, 1.03
    if fav_margin <= -10:
        return 1.06, 0.94
    if fav_margin <= -7:
        return 1.03, 0.96
    return 1.0, 1.0


def _weather_total_adj(wind: float | None, roof: str | None) -> float:
    if roof and str(roof).lower() in ("dome", "closed", "indoors"):
        return 0.0
    if wind is None:
        return 0.0
    try:
        w = float(wind)
    except (TypeError, ValueError):
        return 0.0
    if w >= 20:
        return -4.0
    if w >= 15:
        return -2.5
    if w >= 10:
        return -1.0
    return 0.0


def simulate_nfl_total(
    *,
    home_team: str,
    away_team: str,
    home_rates: TeamDriveRates,
    away_rates: TeamDriveRates,
    market_line: float | None,
    home_spread: float | None = None,
    wind: float | None = None,
    roof: str | None = None,
    rest_adj: float = 0.0,
    n_sims: int = 8000,
    seed: int | None = 42,
) -> TotalsSimResult:
    rng = np.random.default_rng(seed)
    h_pace, a_pace = _game_script_pace_adj(home_spread)
    weather = _weather_total_adj(wind, roof) + rest_adj

    home_drives = max(8.0, home_rates.drives_per_game * h_pace)
    away_drives = max(8.0, away_rates.drives_per_game * a_pace)

    totals = np.zeros(n_sims, dtype=float)
    for i in range(n_sims):
        h_score = _simulate_team_score(home_rates, home_drives, rng)
        a_score = _simulate_team_score(away_rates, away_drives, rng)
        totals[i] = h_score + a_score + weather

    totals = np.maximum(np.rint(totals), 0).astype(float)
    mean = float(np.mean(totals))
    median = float(np.median(totals))
    std = float(np.std(totals))

    p_over = p_under = p_push = None
    lean = None
    if market_line is not None:
        line = float(market_line)
        p_over = float(np.mean(totals > line))
        p_under = float(np.mean(totals < line))
        p_push = float(np.mean(totals == line))
        lean = "over" if median >= line else "under"

    return TotalsSimResult(
        home_team=home_team,
        away_team=away_team,
        n_sims=n_sims,
        sim_mean=mean,
        sim_median=median,
        sim_std=std,
        market_line=market_line,
        p_over=p_over,
        p_under=p_under,
        p_push=p_push,
        sim_lean=lean,
        total_samples=totals,
    )


def _drive_outcome_probs(rates: TeamDriveRates) -> tuple[float, float, float]:
    """(p_td, p_fg, p_empty) with E[points] ≈ pts_per_drive."""
    mu = float(rates.pts_per_drive)
    p_td = float(np.clip(rates.rz_td_rate * 0.22, 0.06, 0.28))
    rem = mu - 7.0 * p_td
    p_fg = float(np.clip(rem / 3.0, 0.08, 0.42))
    if p_td + p_fg > 0.92:
        scale = 0.92 / (p_td + p_fg)
        p_td *= scale
        p_fg *= scale
    return p_td, p_fg, max(0.0, 1.0 - p_td - p_fg)


def _simulate_team_score(rates: TeamDriveRates, n_drives: float, rng: np.random.Generator) -> float:
    n = int(max(1, rng.poisson(n_drives)))
    p_td, p_fg, p_empty = _drive_outcome_probs(rates)
    score = 0.0
    for _ in range(n):
        u = rng.random()
        if u < p_td:
            score += 7.0 if rng.random() < 0.93 else 6.0
        elif u < p_td + p_fg:
            score += 3.0
        else:
            score += 0.0
    return score


def sim_result_to_dict(res: TotalsSimResult, *, blended: float | None = None) -> dict:
    out = {
        "sim_mean": round(res.sim_mean, 2),
        "sim_median": round(res.sim_median, 2),
        "sim_std": round(res.sim_std, 2),
        "market_line": res.market_line,
        "sim_lean": res.sim_lean,
        "n_sims": res.n_sims,
    }
    if res.p_over is not None:
        out["p_over"] = round(res.p_over, 4)
        out["p_under"] = round(res.p_under or 0.0, 4)
        out["p_push"] = round(res.p_push or 0.0, 4)
    if blended is not None:
        out["blended_total"] = round(blended, 2)
    return out
