"""Quarter-Kelly staking with NBA shadow caps."""

from __future__ import annotations

from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.utils.odds import american_to_implied_prob


def full_kelly_fraction(p_true: float, american: float) -> float:
    """Kelly fraction of bankroll (not units)."""
    p = min(max(float(p_true), 1e-6), 1 - 1e-6)
    if american > 0:
        b = american / 100.0
    else:
        b = 100.0 / abs(american)
    q = 1.0 - p
    if b <= 0:
        return 0.0
    return max(0.0, (p * b - q) / b)


def stake_units(
    p_true: float,
    american: float,
    *,
    play_type: str = "side",
    bankroll_units: float = 100.0,
) -> float:
    settings = get_settings()
    kelly = full_kelly_fraction(p_true, american) * settings.nba_kelly_fraction
    raw = kelly * bankroll_units
    cap = settings.nba_cap_game_line_units if play_type != "prop" else settings.nba_cap_prop_units
    return round(min(raw, cap), 3)


def apply_portfolio_caps(
    candidates: list[dict[str, Any]],
    *,
    existing_today_units: float = 0.0,
) -> list[dict[str, Any]]:
    """Enforce per-game and per-night unit caps; drop lowest-edge picks when over."""
    settings = get_settings()
    night_budget = max(0.0, settings.nba_cap_units_per_night - existing_today_units)
    by_game: dict[str, float] = {}
    out: list[dict[str, Any]] = []
    ranked = sorted(candidates, key=lambda c: float(c.get("edge") or 0), reverse=True)
    for c in ranked:
        eid = str(c.get("event_id") or "")
        u = float(c.get("units") or 0)
        if u <= 0:
            continue
        game_used = by_game.get(eid, 0.0)
        if game_used + u > settings.nba_cap_units_per_game:
            room = max(0.0, settings.nba_cap_units_per_game - game_used)
            if room < 0.05:
                continue
            u = round(room, 3)
            c = {**c, "units": u}
        if u > night_budget:
            if night_budget < 0.05:
                continue
            u = round(night_budget, 3)
            c = {**c, "units": u}
        by_game[eid] = by_game.get(eid, 0.0) + u
        night_budget -= u
        out.append(c)
    return out


def price_vs_fair_implied(price: float, p_fair: float | None) -> float | None:
    if p_fair is None:
        return None
    return round(float(p_fair) - american_to_implied_prob(float(price)), 4)
