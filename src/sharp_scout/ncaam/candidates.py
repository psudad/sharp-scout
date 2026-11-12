"""Score slate games and emit qualifying spread/ML candidates."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from sharp_scout.ncaam.model import project_game, simulate_margin, p_cover_side, p_ml_side
from sharp_scout.ncaam.ratings import load_ratings, ratings_for_team
from sharp_scout.ncaam.rules import (
    RULES,
    anchor_k_spread,
    candidate_ev,
    ev_qualifies,
    hook_tiebreak_score,
    model_gap_qualifies,
    price_qualifies,
)
from sharp_scout.phase3.market import anchor_probability, fair_probs_from_two_way, shift_prob_to_line
from sharp_scout.ncaam.margin_sd_shadow import enrich_candidate_shadow
from sharp_scout.utils.odds import american_to_implied_prob, win_prob_to_conditional

logger = logging.getLogger(__name__)

NCAAM_BOOKS = [
    "pinnacle",
    "draftkings",
    "fanduel",
    "betmgm",
    "williamhill_us",
    "espnbet",
    "betrivers",
    "fanatics",
    "bovada",
    "betonlineag",
]


def _pinnacle_spread_age_ok(event: dict[str, Any], now: datetime) -> bool:
    books = event.get("bookmakers") or {}
    pin = books.get("pinnacle")
    if not pin:
        return False
    lu = pin.get("last_update")
    if isinstance(lu, str):
        lu = datetime.fromisoformat(lu.replace("Z", "+00:00"))
    if not isinstance(lu, datetime):
        return False
    if lu.tzinfo is None:
        lu = lu.replace(tzinfo=timezone.utc)
    return (now - lu).total_seconds() <= RULES.pinnacle_max_age_min * 60


def _outcomes_by_side(event: dict[str, Any], market: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
    books = event.get("bookmakers") or {}
    for bkey in NCAAM_BOOKS:
        bm = books.get(bkey)
        if not bm:
            continue
        for o in (bm.get("markets") or {}).get(market) or []:
            side = o.get("side")
            if side not in out:
                continue
            out[side].append(
                {
                    "book": bkey,
                    "price": float(o.get("price")),
                    "line": float(o["point"]) if o.get("point") is not None else None,
                    "last_update": bm.get("last_update"),
                }
            )
    return out


# Moneyline anchor sanity guard (same rule as NBA): placeholder / suspended prices such as
# -10000/-10000 must never become a fair probability.
ML_PRICE_LIMIT = 2000.0
ML_OVERROUND_MIN = 1.00
ML_OVERROUND_MAX = 1.10


def _ml_price_ok(price: float) -> bool:
    if price != price or abs(price) < 100:  # NaN or not a real American price
        return False
    return -ML_PRICE_LIMIT < price < ML_PRICE_LIMIT


def _pinnacle_h2h_fair(event: dict[str, Any], side: str) -> float | None:
    """No-vig Pinnacle moneyline fair win prob for ``side``.

    Uses Pinnacle's two moneyline prices for this game, de-vigged. Returns None (no ML play)
    when Pinnacle has no h2h market, when either side is missing, or when the outcomes cannot
    be matched to exactly one home and one away team. Never falls back to 50%.
    """
    if side not in ("home", "away"):
        return None
    books = event.get("bookmakers") or {}
    pin = books.get("pinnacle")
    if not pin:
        return None
    outs = (pin.get("markets") or {}).get("h2h") or []
    prices: dict[str, float] = {}
    for o in outs:
        s = str(o.get("side"))
        if s not in ("home", "away") or o.get("price") is None:
            return None
        if s in prices:
            return None  # two outcomes claim the same side: cannot trust the mapping
        prices[s] = float(o.get("price"))
    if set(prices) != {"home", "away"}:
        return None
    if not (_ml_price_ok(prices["home"]) and _ml_price_ok(prices["away"])):
        logger.info("ncaam ml anchor rejected: extreme price %s", prices)
        return None
    total = american_to_implied_prob(prices["home"]) + american_to_implied_prob(prices["away"])
    if not (ML_OVERROUND_MIN <= total <= ML_OVERROUND_MAX):
        logger.info("ncaam ml anchor rejected: implied total %.3f %s", total, prices)
        return None
    # fair_probs_from_two_way takes American prices and converts them itself.
    p_home_fair, p_away_fair = fair_probs_from_two_way(prices["home"], prices["away"])
    return p_home_fair if side == "home" else p_away_fair


def _pinnacle_fair_spread(
    event: dict[str, Any], side: str, line: float, sd: float
) -> tuple[float | None, float | None]:
    """No-vig Pinnacle spread fair cover prob for ``side`` at ``line``; (None, None) if unavailable."""
    books = event.get("bookmakers") or {}
    pin = books.get("pinnacle")
    if not pin:
        return None, None
    outs = (pin.get("markets") or {}).get("spreads") or []
    home_line = None
    prices: dict[str, float] = {}
    for o in outs:
        if o.get("side") not in ("home", "away") or o.get("price") is None:
            continue
        prices[str(o.get("side"))] = float(o.get("price"))
        if o.get("side") == "home" and o.get("point") is not None:
            home_line = float(o.get("point"))
    if home_line is None or "home" not in prices or "away" not in prices:
        return None, None
    # fair_probs_from_two_way takes American prices and converts them itself.
    p_home_fair, _ = fair_probs_from_two_way(prices["home"], prices["away"])
    p_side, _ = shift_prob_to_line(
        p_home_fair if side == "home" else 1.0 - p_home_fair,
        market="spreads",
        side=side,
        ref_line=home_line if side == "home" else -home_line,
        line=line,
        sd=sd,
    )
    return p_side, home_line


def _beat_open(side: str, line: float, open_line: float | None) -> bool:
    if open_line is None:
        return False
    # Line moved our way: dog getting more points, fav laying fewer.
    if side == "away":
        return line > open_line
    return line > open_line  # home spread: less negative is better


def evaluate_game(
    game: dict[str, Any],
    event: dict[str, Any],
    ratings: dict[str, dict[str, float]],
    *,
    now: datetime | None = None,
    open_lines: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    if not _pinnacle_spread_age_ok(event, now):
        return []
    hr = ratings_for_team(game["home_team"], ratings)
    ar = ratings_for_team(game["away_team"], ratings)
    if not hr or not ar:
        return []
    proj = project_game(
        home_team=game["home_team"],
        away_team=game["away_team"],
        home_ratings=hr,
        away_ratings=ar,
        neutral_site=bool(game.get("neutral_site")),
    )
    margins = simulate_margin(proj)
    expected_poss = float(getattr(proj, "poss", 0.0) or 0.0)
    pin_home_line = None
    pin = (event.get("bookmakers") or {}).get("pinnacle") or {}
    pin_spread_prices: dict[str, float] = {}
    for o in (pin.get("markets") or {}).get("spreads") or []:
        if o.get("side") == "home" and o.get("point") is not None and pin_home_line is None:
            pin_home_line = float(o["point"])
        if o.get("side") in ("home", "away") and o.get("price") is not None:
            pin_spread_prices[str(o.get("side"))] = float(o.get("price"))
    if pin_home_line is None:
        return []
    if not model_gap_qualifies(proj.margin_model, pin_home_line):
        return []

    k = anchor_k_spread(now)
    cands: list[dict[str, Any]] = []
    p_home_fair_pin: float | None = None
    if set(pin_spread_prices) == {"home", "away"}:
        p_home_fair_pin, _ = fair_probs_from_two_way(
            pin_spread_prices["home"], pin_spread_prices["away"]
        )

    spread_out = _outcomes_by_side(event, "spreads")
    for side in ("home", "away"):
        for offer in spread_out[side]:
            line = offer["line"]
            price = offer["price"]
            if line is None or not price_qualifies(price, market="spreads"):
                continue
            p_mod, p_push = p_cover_side(margins, side, line)
            p_fair, _ = _pinnacle_fair_spread(event, side, line, RULES.margin_sd)
            if p_fair is None:
                continue
            p_true = anchor_probability(p_mod, p_fair, k, RULES.anchor_tilt_cap)
            p_cond = win_prob_to_conditional(p_true, p_push)
            ev = candidate_ev(p_cond, price, p_push)
            if not ev_qualifies(ev):
                continue
            open_key = f"{game.get('espn_id')}:{side}"
            row = {
                "event_id": event.get("event_id") or game.get("odds_event_id"),
                "espn_id": game.get("espn_id"),
                "market": "spreads",
                "side": side,
                "line": line,
                "price": price,
                "book": offer["book"],
                "ev": ev,
                "p_true": round(p_true, 4),
                "p_model": p_mod,
                "p_fair": p_fair,
                "p_push": p_push,
                "model_margin": proj.margin_model,
                "projected_poss": round(expected_poss, 3),
                "hook_score": hook_tiebreak_score(side, line),
                "beat_open": _beat_open(side, line, (open_lines or {}).get(open_key)),
                "selection": game[f"{side}_team"],
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "tip": game.get("commence_time"),
            }
            enrich_candidate_shadow(
                row,
                expected_poss=expected_poss,
                p_mod_live=p_mod,
                p_push=p_push,
                p_home_fair_pin=p_home_fair_pin,
                home_spread_pin=pin_home_line,
                k=k,
                now=now,
            )
            cands.append(row)

    # ML only if spread did not already qualify with higher EV — handled in pick_best per game later.
    h2h_out = _outcomes_by_side(event, "h2h")
    for side in ("home", "away"):
        for offer in h2h_out[side]:
            price = offer["price"]
            if not price_qualifies(price, market="h2h"):
                continue
            p_mod, p_push = p_ml_side(margins, side)
            p_fair = _pinnacle_h2h_fair(event, side)
            if p_fair is None:
                continue
            p_true = anchor_probability(p_mod, p_fair, k, RULES.anchor_tilt_cap)
            p_cond = win_prob_to_conditional(p_true, p_push)
            ev = candidate_ev(p_cond, price, p_push)
            if not ev_qualifies(ev):
                continue
            row = {
                "event_id": event.get("event_id"),
                "espn_id": game.get("espn_id"),
                "market": "h2h",
                "side": side,
                "line": None,
                "price": price,
                "book": offer["book"],
                "ev": ev,
                "p_true": round(p_true, 4),
                "p_model": p_mod,
                "p_fair": p_fair,
                "p_push": p_push,
                "model_margin": proj.margin_model,
                "projected_poss": round(expected_poss, 3),
                "hook_score": 0,
                "beat_open": False,
                "selection": game[f"{side}_team"],
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "tip": game.get("commence_time"),
            }
            enrich_candidate_shadow(
                row,
                expected_poss=expected_poss,
                p_mod_live=p_mod,
                p_push=p_push,
                p_home_fair_pin=p_home_fair_pin,
                home_spread_pin=pin_home_line,
                k=k,
                now=now,
            )
            cands.append(row)
    return cands


def _market_rank(market: str) -> int:
    """Higher wins: spreads first; ML only when no spread qualifies for the game."""
    return 1 if market == "spreads" else 0


def pick_best_per_game(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for c in candidates:
        gid = str(c.get("espn_id") or "")
        cur = best.get(gid)
        if cur is None:
            best[gid] = c
            continue
        key = (_market_rank(str(c.get("market"))), c["ev"], c.get("hook_score", 0))
        cur_key = (_market_rank(str(cur.get("market"))), cur["ev"], cur.get("hook_score", 0))
        if key > cur_key:
            best[gid] = c
    return best
