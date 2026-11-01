"""Blended Jan–Feb NCAAM qualification, line choice, sizing, and daily caps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sharp_scout.utils.odds import expected_value_with_push

ET = ZoneInfo("America/New_York")
MODEL_VERSION = "ncaam-blended-janfeb-v1"


@dataclass(frozen=True)
class BlendedRules:
    hfa: float = 3.0
    margin_sd: float = 10.5
    total_sd: float = 14.0
    mc_sims: int = 10_000
    ev_min: float = 0.03
    ev_boost_stake: float = 0.06
    price_floor: float = -150.0
    ml_price_min: float = -150.0
    ml_price_max: float = 200.0
    model_market_gap_max: float = 8.0
    pinnacle_max_age_min: float = 60.0
    daily_cap_plays: int = 8
    stake_standard: float = 1.0
    stake_boost: float = 1.5
    max_units_per_play: float = 1.5
    max_units_per_day: float = 8.0
    anchor_k_after_dec1: float = 0.15
    anchor_k_early: float = 0.10
    anchor_dec1_et: date = date(2026, 12, 1)
    anchor_tilt_cap: float = 0.03
    whale_gap_tag: float = 12.0
    p_true_display_cap: float = 0.80
    whole_line_juice_cents: float = 10.0


RULES = BlendedRules()


def anchor_k_spread(when: datetime | None = None) -> float:
    when = when or datetime.now(ET)
    if when.tzinfo is None:
        when = when.replace(tzinfo=ET)
    else:
        when = when.astimezone(ET)
    if when.date() < RULES.anchor_dec1_et:
        return RULES.anchor_k_early
    return RULES.anchor_k_after_dec1


def price_qualifies(price: float, *, market: str) -> bool:
    if price >= RULES.price_floor:
        return True
    if market == "h2h" and RULES.ml_price_min <= price <= RULES.ml_price_max:
        return True
    return False


def ev_qualifies(ev: float) -> bool:
    return ev >= RULES.ev_min


def model_gap_qualifies(model_margin: float, home_spread: float) -> bool:
    """|margin_model − implied market margin| ≤ 8 (home spread = negative when favored)."""
    market_margin = -float(home_spread)
    return abs(float(model_margin) - market_margin) <= RULES.model_market_gap_max


def hook_tiebreak_score(side: str, line: float) -> int:
    """Prefer +X.5 dog or −2.5 fav at equal EV."""
    if side == "away" and line > 0 and abs((line * 10) % 10 - 5) < 1e-6:
        return 2
    if side == "home" and line < 0 and abs(line + 2.5) < 1e-6:
        return 2
    return 0


def stake_units(*, ev: float, beat_open: bool, units_already_today: float) -> float:
    u = RULES.stake_standard
    if ev >= RULES.ev_boost_stake and beat_open:
        u = RULES.stake_boost
    u = min(u, RULES.max_units_per_play)
    if units_already_today + u > RULES.max_units_per_day:
        u = max(0.0, RULES.max_units_per_day - units_already_today)
    return round(u, 2)


def apply_daily_cap(candidates: list[dict], *, et_day: date) -> list[dict]:
    """Keep top EV plays up to daily cap and 8u."""
    day_rows = [c for c in candidates if c.get("et_day") == et_day.isoformat()]
    day_rows.sort(key=lambda c: (-float(c.get("ev") or 0), -hook_tiebreak_score(
        str(c.get("side")), float(c.get("line") or 0))))
    out: list[dict] = []
    units = 0.0
    games: set[str] = set()
    for c in day_rows:
        gid = str(c.get("event_id") or c.get("espn_id") or "")
        if gid in games:
            continue
        u = stake_units(
            ev=float(c.get("ev") or 0),
            beat_open=bool(c.get("beat_open")),
            units_already_today=units,
        )
        if u <= 0:
            break
        games.add(gid)
        row = {**c, "units": u}
        out.append(row)
        units += u
        if len(out) >= RULES.daily_cap_plays:
            break
    return out


def display_confidence(p_true: float) -> float:
    return min(max(float(p_true), 0.5), RULES.p_true_display_cap)


def candidate_ev(p_true: float, price: float, p_push: float = 0.0) -> float:
    return expected_value_with_push(p_true, price, p_push)
