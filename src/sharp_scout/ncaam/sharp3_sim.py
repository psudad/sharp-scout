"""Monte Carlo cover/ML projection for Sharp 3 lab display only.

Uses the same efficiency × tempo projection and margin noise as the New System
(``sharp_scout.ncaam.model`` + ``RULES``). Does not affect Sharp 3 gates, tiers,
units, or locking. When ratings or a bet line are missing, returns unavailable —
never a synthetic win-loss string.

**Ratings (caller-supplied, typically daily Barttorvik CSV in the runner):**
- Unknown / unmapped team → ``unavailable`` (``missing_team_ratings``).
- This module does **not** fetch ratings and does **not** detect stale cache age;
  stale efficiency rows are a data-ops risk, not corrected here.
- Juice / ``price_estimated`` buy-point quotes are **never** simulation inputs.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import numpy as np

from sharp_scout.ncaam.model import project_game, simulate_margin
from sharp_scout.ncaam.ratings import ratings_for_team
from sharp_scout.ncaam.rules import RULES

SIM_MODEL_ID = "torvik-efficiency-mc-v1"
_LEGACY_SIM_REC = re.compile(r"^\d+-\d+$")


def seed_inputs(espn_id: str, *, side: str, market: str, line: float | None) -> str:
    return f"sharp3-sim|{espn_id}|{side}|{market}|{line}"


def _seed(espn_id: str, *, side: str, market: str, line: float | None) -> int:
    return int(hashlib.sha256(seed_inputs(espn_id, side=side, market=market, line=line).encode()).hexdigest()[:12], 16)


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
    seed_blob = seed_inputs(eid, side=side, market=mkt, line=line)
    seed_val = _seed(eid, side=side, market=mkt, line=line)
    rng = np.random.default_rng(seed_val)
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
        "reproducibility": {
            "seed": seed_val,
            "seed_inputs": seed_blob,
            "rng": "numpy.random.Generator",
        },
        "ratings_policy": (
            "Caller-supplied Torvik efficiency map; missing teams → unavailable. "
            "Cache staleness is not validated in this module."
        ),
    }


def is_valid_sim_projection(projection: Any) -> bool:
    """True only for a complete real MC payload (guards lab renderer)."""
    if not isinstance(projection, dict) or projection.get("status") != "ok":
        return False
    if projection.get("kind") != "projection" or projection.get("model") != SIM_MODEL_ID:
        return False
    n = projection.get("n")
    if not isinstance(n, int) or n <= 0:
        return False
    for key in ("wins", "losses", "pushes"):
        if not isinstance(projection.get(key), int) or projection[key] < 0:
            return False
    if projection["wins"] + projection["losses"] + projection["pushes"] != n:
        return False
    rep = projection.get("reproducibility") or {}
    if not rep.get("seed_inputs") or rep.get("seed") is None:
        return False
    return True


def is_legacy_fabricated_sim_rec(sim_rec: Any) -> bool:
    """Pre-Torvik-MC Sharp 3 display strings (confidence Bernoulli)."""
    if not isinstance(sim_rec, str) or not sim_rec.strip():
        return False
    if sim_rec.startswith("proj "):
        return False
    return bool(_LEGACY_SIM_REC.match(sim_rec.strip()))


def lab_sim_unavailable_reason(p: dict[str, Any]) -> str:
    proj = p.get("sim_projection")
    if isinstance(proj, dict) and proj.get("status") == "unavailable":
        return str(proj.get("reason") or "unavailable")
    if is_legacy_fabricated_sim_rec(p.get("sim_rec")) or (
        p.get("sim_rec") and not is_valid_sim_projection(proj)
    ):
        return "legacy_synthetic_not_displayed"
    if p.get("sim_rec") and not is_valid_sim_projection(proj):
        return "missing_sim_projection_metadata"
    return "unavailable"


def lab_sim_display_text(p: dict[str, Any]) -> str | None:
    """Plain-text sim line for lab HTML (never shows legacy pseudo-data)."""
    if p.get("sim_rec") is None and p.get("sim_projection") is None:
        return None
    proj = p.get("sim_projection")
    if is_valid_sim_projection(proj):
        rec = format_sim_rec(proj)
        model = proj.get("model")
        n = proj.get("n")
        p_cov = proj.get("p_cover_or_ml")
        extra = f" · p≈{p_cov}" if p_cov is not None else ""
        return f"MC projection (not graded record): {rec} · {model} · n={n}{extra}"
    reason = lab_sim_unavailable_reason(p)
    if reason == "legacy_synthetic_not_displayed":
        return "MC projection: unavailable (legacy synthetic sim_rec — not shown)"
    return f"MC projection: unavailable ({reason})"


def format_sim_rec(projection: dict[str, Any]) -> str | None:
    """Human-readable projection label (not ledger W-L)."""
    if projection.get("status") != "ok":
        return None
    w, l, p, n = projection["wins"], projection["losses"], projection["pushes"], projection["n"]
    core = f"proj {w}-{l}" + (f"-{p}" if p else "")
    return f"{core}/{n} MC"
