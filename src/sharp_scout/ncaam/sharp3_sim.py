"""Monte Carlo cover/ML projection for Sharp 3 lab display only.

Uses the same efficiency × tempo projection and margin noise as the New System
(``sharp_scout.ncaam.model`` + ``RULES``). Does not affect Sharp 3 gates, tiers,
units, or locking. When ratings or a bet line are missing, returns unavailable —
never a synthetic win-loss string.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from sharp_scout.ncaam.model import project_game, simulate_margin
from sharp_scout.ncaam.ratings import ratings_for_team
from sharp_scout.ncaam.rules import RULES

SIM_MODEL_ID = "torvik-efficiency-mc-v1"


def _seed(espn_id: str, *, side: str, market: str, line: float | None) -> int:
    blob = f"sharp3-sim|{espn_id}|{side}|{market}|{line}"
    return int(hashlib.sha256(blob.encode()).hexdigest()[:12], 16)


def _count_spread_outcomes(margins: np.ndarray, *, side: str, line: float) -> tuple[int, int, int]:
    if side == "home":
        diff = margins + float(line)
    else:
        diff = -margins + float(line)
    wins = int(np.sum(diff > 0))
    pushes = int(np.sum(np.isclose(diff, 0.0)))
    losses = int(len(margins) - wins - pushes)
    return wins, losses, pushes


def _count_ml_outcomes(margins: np.ndarray, *, side: str) -> tuple[int, int, int]:
    w, p = p_ml_side(margins, side)
    n = len(margins)
    # Exact counts from draws (not rounded probabilities).
    if side == "home":
        wins = int(np.sum(margins > 0))
        pushes = int(np.sum(margins == 0))
    else:
        wins = int(np.sum(margins < 0))
        pushes = int(np.sum(margins == 0))
    losses = n - wins - pushes
    return wins, losses, pushes


def monte_carlo_projection(
    game: dict[str, Any],
    *,
    side: str,
    market: str,
    line: float | None,
    ratings: dict[str, dict[str, float]] | None,
    n: int | None = None,
) -> dict[str, Any]:
    """Run ``n`` margin draws; return structured projection or unavailable."""
    n = int(n or RULES.mc_sims)
    eid = str(game.get("espn_id") or "")
    home = str(game.get("home_team") or "")
    away = str(game.get("away_team") or "")
    if not ratings:
        return {"status": "unavailable", "reason": "ratings_not_loaded"}
    if not home or not away:
        return {"status": "unavailable", "reason": "missing_teams"}
    hr = ratings_for_team(home, ratings)
    ar = ratings_for_team(away, ratings)
    if not hr or not ar:
        return {"status": "unavailable", "reason": "missing_team_ratings"}
    mkt = market or "spreads"
    if mkt == "spreads" and line is None:
        return {"status": "unavailable", "reason": "missing_spread_line"}
    neutral = bool(game.get("neutral_site"))
    proj = project_game(
        home_team=home,
        away_team=away,
        home_ratings=hr,
        away_ratings=ar,
        neutral_site=neutral,
        hfa=RULES.hfa,
    )
    rng = np.random.default_rng(_seed(eid, side=side, market=mkt, line=line))
    margins = simulate_margin(proj, n=n, rng=rng)
    if mkt == "h2h":
        wins, losses, pushes = _count_ml_outcomes(margins, side=side)
        p_hit = (wins + 0.5 * pushes) / n if n else None
    else:
        wins, losses, pushes = _count_spread_outcomes(margins, side=side, line=float(line))
        p_hit = (wins + 0.5 * pushes) / n if n else None
    return {
        "status": "ok",
        "kind": "projection",
        "model": SIM_MODEL_ID,
        "n": n,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "p_cover_or_ml": round(p_hit, 4) if p_hit is not None else None,
        "margin_model": round(proj.margin_model, 2),
        "margin_sd": RULES.margin_sd,
        "hfa": 0.0 if neutral else RULES.hfa,
        "inputs": {
            "espn_id": eid,
            "side": side,
            "market": mkt,
            "line": line,
            "neutral_site": neutral,
            "note": "Juice/price not used; spread/ML result vs locked line only.",
        },
    }


def format_sim_rec(projection: dict[str, Any]) -> str | None:
    """Human-readable projection label (not ledger W-L)."""
    if projection.get("status") != "ok":
        return None
    w, l, p, n = projection["wins"], projection["losses"], projection["pushes"], projection["n"]
    core = f"proj {w}-{l}" + (f"-{p}" if p else "")
    return f"{core}/{n} MC"
