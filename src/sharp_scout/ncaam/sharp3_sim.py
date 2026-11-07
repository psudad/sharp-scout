"""Monte Carlo cover/ML projection for Sharp 3 lab display only.

Uses the same efficiency × tempo projection and margin noise as the New System
(``sharp_scout.ncaam.model`` + ``RULES``). Does not affect Sharp 3 gates, tiers,
units, or locking. When ratings or a bet line are missing, returns unavailable —
never a synthetic win-loss string.

**Ratings as-of (Sharp 3 display only):**
Barttorvik ``team_results`` CSV has **no** snapshot/as-of column. Local
``ratings_YYYYMMDD.csv`` names are **cache acquisition labels** only (see
``ensure_daily_ratings``). HTTP ``Last-Modified`` is stored as audit metadata
but is **not** ``ratings_as_of``. MC display requires ``ratings_as_of_verified``
from upstream ``ratings_source_as_of`` in fetch metadata (unset today).
- Unknown / unmapped team → ``unavailable`` (``missing_team_ratings``).
- Juice / ``price_estimated`` buy-point quotes are **never** simulation inputs.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from sharp_scout.ncaam.model import project_game, simulate_margin
from sharp_scout.ncaam.ratings import ratings_for_team
from sharp_scout.ncaam.rules import RULES

SIM_MODEL_ID = "torvik-efficiency-mc-v1"
_LEGACY_SIM_REC = re.compile(r"^\d+-\d+$")
ET = ZoneInfo("America/New_York")

# Lab-only display policy: requires verified upstream as-of (none available from Torvik today).
DISPLAY_POLICY_ID = "sharp3-display-ratings-asof-v2"
DISPLAY_MAX_RATING_AGE_DAYS = 1  # applies only when ratings_as_of_verified is true
DISPLAY_POLICY_REVIEW = (
    "Torvik CSV provides no model snapshot date. cache_date_et is acquisition label only. "
    "Production MC display stays unavailable until ratings_source_as_of is populated from "
    "a verified upstream field (not HTTP Last-Modified or filename)."
)


def validate_ratings_for_sharp3_display(
    provenance: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    if not provenance:
        return False, "ratings_provenance_missing"
    if not provenance.get("ratings_as_of_verified"):
        return False, "ratings_as_of_missing"
    as_of_s = provenance.get("ratings_as_of")
    if not as_of_s:
        return False, "ratings_as_of_missing"
    try:
        as_of = date.fromisoformat(str(as_of_s))
    except ValueError:
        return False, "ratings_as_of_invalid"
    now = now or datetime.now(timezone.utc)
    today_et = now.astimezone(ET).date()
    if as_of > today_et:
        return False, "ratings_as_of_in_future"
    age_days = (today_et - as_of).days
    if age_days > DISPLAY_MAX_RATING_AGE_DAYS:
        return False, "ratings_stale_for_display"
    return True, ""


def _unavailable(
    reason: str,
    *,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "unavailable", "reason": reason}
    if provenance is not None:
        out["ratings_provenance"] = provenance
    out["ratings_display_policy"] = DISPLAY_POLICY_ID
    out["ratings_display_policy_note"] = DISPLAY_POLICY_REVIEW
    return out


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


def run_margin_monte_carlo_core(
    game: dict[str, Any],
    *,
    side: str,
    market: str,
    line: float | None,
    ratings: dict[str, dict[str, float]],
    ratings_provenance: dict[str, Any] | None = None,
    n: int | None = None,
) -> dict[str, Any]:
    """Run margin MC only (unit tests / labeled math demos). No provenance gate."""
    n = int(n or RULES.mc_sims)
    eid = str(game.get("espn_id") or "")
    home = str(game.get("home_team") or "")
    away = str(game.get("away_team") or "")
    hr = ratings_for_team(home, ratings)
    ar = ratings_for_team(away, ratings)
    if not hr or not ar:
        raise ValueError("missing_team_ratings")
    mkt = market or "spreads"
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
        "ratings_provenance": ratings_provenance,
        "ratings_display_policy": DISPLAY_POLICY_ID,
        "ratings_display_policy_note": DISPLAY_POLICY_REVIEW,
        "ratings_display_max_age_days": DISPLAY_MAX_RATING_AGE_DAYS,
    }


def monte_carlo_projection(
    game: dict[str, Any],
    *,
    side: str,
    market: str,
    line: float | None,
    ratings: dict[str, dict[str, float]] | None,
    ratings_provenance: dict[str, Any] | None = None,
    now: datetime | None = None,
    n: int | None = None,
) -> dict[str, Any]:
    """Run ``n`` margin draws; return structured projection or unavailable."""
    fresh, fresh_reason = validate_ratings_for_sharp3_display(ratings_provenance, now=now)
    if not fresh:
        return _unavailable(fresh_reason, provenance=ratings_provenance)
    if not ratings:
        return _unavailable("ratings_not_loaded", provenance=ratings_provenance)
    if not game.get("home_team") or not game.get("away_team"):
        return _unavailable("missing_teams", provenance=ratings_provenance)
    mkt = market or "spreads"
    if mkt == "spreads" and line is None:
        return _unavailable("missing_spread_line", provenance=ratings_provenance)
    try:
        return run_margin_monte_carlo_core(
            game,
            side=side,
            market=mkt,
            line=line,
            ratings=ratings,
            ratings_provenance=ratings_provenance,
            n=n,
        )
    except ValueError:
        return _unavailable("missing_team_ratings", provenance=ratings_provenance)


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
    rprov = projection.get("ratings_provenance") or {}
    if not rprov.get("ratings_as_of_verified") or not rprov.get("ratings_as_of") or not rprov.get("source"):
        return False
    if projection.get("ratings_display_policy") != DISPLAY_POLICY_ID:
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
