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
    display_confidence,
    ev_qualifies,
    hook_tiebreak_score,
    model_gap_qualifies,
    price_qualifies,
)
from sharp_scout.phase3.market import anchor_probability, fair_probs_from_two_way, shift_prob_to_line
from sharp_scout.utils.odds import win_prob_to_conditional

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


def _pinnacle_fair_spread(event: dict[str, Any], side: str, line: float, sd: float) -> tuple[float, float]:
    books = event.get("bookmakers") or {}
    pin = books.get("pinnacle")
    if not pin:
        return 0.5, 0.0
    outs = (pin.get("markets") or {}).get("spreads") or []
    home_line = None
    prices: dict[str, float] = {}
    for o in outs:
        prices[str(o.get("side"))] = float(o.get("price"))
        if o.get("side") == "home":
            home_line = float(o.get("point"))
    if home_line is None or "home" not in prices or "away" not in prices:
        return 0.5, 0.0
    from sharp_scout.utils.odds import american_to_implied_prob

    ph = american_to_implied_prob(prices["home"])
    pa = american_to_implied_prob(prices["away"])
    p_home_fair, _ = fair_probs_from_two_way(ph, pa)
    ref_line = home_line if side == "home" else -home_line
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
    pin_home_line = None
    pin = (event.get("bookmakers") or {}).get("pinnacle") or {}
    for o in (pin.get("markets") or {}).get("spreads") or []:
        if o.get("side") == "home" and o.get("point") is not None:
            pin_home_line = float(o["point"])
            break
    if pin_home_line is None:
        return []
    if not model_gap_qualifies(proj.margin_model, pin_home_line):
        return []

    k = anchor_k_spread(now)
    cands: list[dict[str, Any]] = []
    spread_out = _outcomes_by_side(event, "spreads")
    for side in ("home", "away"):
        for offer in spread_out[side]:
            line = offer["line"]
            price = offer["price"]
            if line is None or not price_qualifies(price, market="spreads"):
                continue
            p_mod, p_push = p_cover_side(margins, side, line)
            p_fair, _ = _pinnacle_fair_spread(event, side, line, RULES.margin_sd)
            p_true = anchor_probability(p_mod, p_fair, k, RULES.anchor_tilt_cap)
            p_cond = win_prob_to_conditional(p_true, p_push)
            ev = candidate_ev(p_cond, price, p_push)
            if not ev_qualifies(ev):
                continue
            open_key = f"{game.get('espn_id')}:{side}"
            cands.append(
                {
                    "event_id": event.get("event_id") or game.get("odds_event_id"),
                    "espn_id": game.get("espn_id"),
                    "market": "spreads",
                    "side": side,
                    "line": line,
                    "price": price,
                    "book": offer["book"],
                    "ev": ev,
                    "p_true": display_confidence(p_true),
                    "p_model": p_mod,
                    "p_fair": p_fair,
                    "p_push": p_push,
                    "model_margin": proj.margin_model,
                    "hook_score": hook_tiebreak_score(side, line),
                    "beat_open": _beat_open(side, line, (open_lines or {}).get(open_key)),
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "tip": game.get("commence_time"),
                }
            )

    # ML only if spread did not already qualify with higher EV — handled in pick_best per game later.
    h2h_out = _outcomes_by_side(event, "h2h")
    for side in ("home", "away"):
        for offer in h2h_out[side]:
            price = offer["price"]
            if not price_qualifies(price, market="h2h"):
                continue
            p_mod, p_push = p_ml_side(margins, side)
            # Devig pinnacle h2h
            books = event.get("bookmakers") or {}
            pin = books.get("pinnacle") or {}
            outs = (pin.get("markets") or {}).get("h2h") or []
            prices = {str(o.get("side")): float(o.get("price")) for o in outs}
            if "home" in prices and "away" in prices:
                from sharp_scout.utils.odds import american_to_implied_prob

                ph = american_to_implied_prob(prices["home"])
                pa = american_to_implied_prob(prices["away"])
                p_home_fair, _ = fair_probs_from_two_way(ph, pa)
                p_fair = p_home_fair if side == "home" else 1.0 - p_home_fair
            else:
                p_fair = 0.5
            p_true = anchor_probability(p_mod, p_fair, k, RULES.anchor_tilt_cap)
            p_cond = win_prob_to_conditional(p_true, p_push)
            ev = candidate_ev(p_cond, price, p_push)
            if not ev_qualifies(ev):
                continue
            cands.append(
                {
                    "event_id": event.get("event_id"),
                    "espn_id": game.get("espn_id"),
                    "market": "h2h",
                    "side": side,
                    "line": None,
                    "price": price,
                    "book": offer["book"],
                    "ev": ev,
                    "p_true": display_confidence(p_true),
                    "p_model": p_mod,
                    "p_fair": p_fair,
                    "p_push": p_push,
                    "model_margin": proj.margin_model,
                    "hook_score": 0,
                    "beat_open": False,
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "tip": game.get("commence_time"),
                }
            )
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
