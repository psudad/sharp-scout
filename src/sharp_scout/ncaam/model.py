"""Efficiency × tempo projection and Monte Carlo cover probabilities."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sharp_scout.ncaam.rules import RULES


@dataclass
class Projection:
    home_team: str
    away_team: str
    mu_home: float
    mu_away: float
    margin_model: float
    total_model: float
    poss: float


def project_game(
    *,
    home_team: str,
    away_team: str,
    home_ratings: dict[str, float],
    away_ratings: dict[str, float],
    neutral_site: bool = False,
    hfa: float | None = None,
) -> Projection:
    lg_adjt = home_ratings["lg_adjt"]
    lg_eff = home_ratings["lg_eff"]
    poss = home_ratings["adjt"] * away_ratings["adjt"] / max(lg_adjt, 1.0)
    hfa = 0.0 if neutral_site else (RULES.hfa if hfa is None else float(hfa))
    pts_h = home_ratings["adjoe"] * away_ratings["adjde"] / lg_eff * poss / 100.0 + hfa / 2.0
    pts_a = away_ratings["adjoe"] * home_ratings["adjde"] / lg_eff * poss / 100.0 - hfa / 2.0
    return Projection(
        home_team=home_team,
        away_team=away_team,
        mu_home=float(pts_h),
        mu_away=float(pts_a),
        margin_model=float(pts_h - pts_a),
        total_model=float(pts_h + pts_a),
        poss=float(poss),
    )


def simulate_margin(
    proj: Projection,
    *,
    n: int | None = None,
    rng: np.random.Generator | None = None,
    sd: float | None = None,
) -> np.ndarray:
    n = n or RULES.mc_sims
    rng = rng or np.random.default_rng()
    sd = RULES.margin_sd if sd is None else float(sd)
    # Bivariate normal on margin with mean = model margin.
    noise = rng.normal(0.0, sd, size=n)
    return proj.margin_model + noise


def p_cover_home(margins: np.ndarray, home_line: float) -> tuple[float, float]:
    """P(home covers home_line) and P(push) for whole numbers."""
    wins = margins + float(home_line) > 0
    pushes = np.isclose(margins + float(home_line), 0.0)
    return float(np.mean(wins)), float(np.mean(pushes))


def p_cover_side(margins: np.ndarray, side: str, line: float) -> tuple[float, float]:
    if side == "home":
        return p_cover_home(margins, line)
    p_h, p_push = p_cover_home(margins, -line)
    return 1.0 - p_h - p_push, p_push


def p_ml_side(margins: np.ndarray, side: str) -> tuple[float, float]:
    if side == "home":
        return float(np.mean(margins > 0)), float(np.mean(margins == 0))
    return float(np.mean(margins < 0)), float(np.mean(margins == 0))
