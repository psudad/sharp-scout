"""Sharp 3: the original splits-driven rules (public name "Sharp 3").

Deterministic port of the archived prompt's logic_gates. The hook flags follow what was
actually played: a -X.5 favorite pivots to the moneyline when the ML is better than -170,
otherwise the half point is bought (bet at -X). Only the road-favorite, juice-cap and
trap-hook flags send a play to the Trap list.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sharp_scout.ncaam.sharp3_sim import format_sim_rec, monte_carlo_projection
from sharp_scout.ncaam.splits import has_splits

ENGINE = "sharp3"
PUBLIC_NAME = "Sharp 3"
MODEL_VERSION = "sharp3-v1"

BASE_CONF = 0.72
PIVOT_ML_ABOVE = -170.0
BUY_POINT_EDGE = 6.0
BUY_POINT_EST_PRICE = -130.0
VIG_CAP_MID_MAJOR = -165.0
VIG_CAP_OTHER = -150.0
ROAD_TRAP_LINE = -7.5
TRAP_FLAGS = frozenset({"ROAD_7_TRAP", "JUICE_TRAP", "TRAP_HOOK"})
TIER_RANK = {"TRAP": 0, "BRONZE": 1, "GOLD": 2, "DIAMOND": 3, "DOUBLE_DIAMOND": 4}
SOURCE_BOOKS = (
    "draftkings",
    "fanduel",
    "pinnacle",
    "betmgm",
    "williamhill_us",
    "espnbet",
    "betrivers",
    "fanatics",
    "bovada",
    "betonlineag",
)


def implied_prob(price: float) -> float:
    return abs(price) / (abs(price) + 100.0) if price < 0 else 100.0 / (price + 100.0)


def confidence(money_pct: float, ticket_pct: float) -> float:
    conf = BASE_CONF
    if money_pct > ticket_pct:
        conf += (money_pct - ticket_pct) / 200.0
    if money_pct > 60:
        conf += 0.05
    return conf


def tier_and_units(*, money_pct: float, conf: float, edge: float, trap: bool) -> tuple[str, float]:
    tier = "BRONZE"
    if money_pct > 55 and conf > 0.80 and edge > 5 and not trap:
        tier = "DOUBLE_DIAMOND" if (conf >= 0.90 and edge >= 10) else "DIAMOND"
    elif conf > 0.70 or edge > 4:
        tier = "GOLD" if not trap else "TRAP"
    units = 0.5
    if tier == "DOUBLE_DIAMOND":
        units = min(10.0, max(5.0, 5.0 + (edge - 10.0) * 0.5))
    elif tier == "DIAMOND":
        units = min(4.0, 2.0 + (edge - 5.0) * 0.5)
    elif tier == "GOLD":
        units = min(2.0, 1.0 + (edge - 4.0) * 0.2)
    elif tier == "TRAP":
        units = 0.0
    return tier, round(units, 1)


def _is_hook(line: float) -> bool:
    return abs(abs(line) % 1 - 0.5) < 1e-9


def logic_gates(
    *,
    line: float,
    price: float,
    money_pct: float,
    ticket_pct: float,
    is_mid_major: bool,
    is_road: bool,
    ml_price: float | None = None,
    ml_money_pct: float | None = None,
    ml_ticket_pct: float | None = None,
    alt_price: float | None = None,
) -> dict[str, Any]:
    """Run the gates for one picked side. Returns the bet (market/line/price) and tier."""
    flags: list[str] = []
    market, bet_line, bet_price = "spreads", line, price
    price_estimated = False
    m_pct, t_pct = money_pct, ticket_pct
    conf0 = confidence(money_pct, ticket_pct)
    edge0 = (conf0 - implied_prob(price)) * 100.0
    if line < 0 and _is_hook(line):
        if ml_price is not None and ml_price > PIVOT_ML_ABOVE:
            flags.append("PIVOT_TO_ML")
            market, bet_line, bet_price = "h2h", None, ml_price
            if ml_money_pct is not None and ml_ticket_pct is not None:
                m_pct, t_pct = ml_money_pct, ml_ticket_pct
        elif edge0 > BUY_POINT_EDGE:
            flags.append("BUY_POINT")
            bet_line = line + 0.5
            if alt_price is not None:
                bet_price = alt_price
            else:
                bet_price = BUY_POINT_EST_PRICE
                price_estimated = True
        else:
            flags.append("TRAP_HOOK")
    if market == "spreads" and is_road and line <= ROAD_TRAP_LINE and not is_mid_major:
        flags.append("ROAD_7_TRAP")
    cap = VIG_CAP_MID_MAJOR if is_mid_major else VIG_CAP_OTHER
    if bet_price < cap:
        flags.append("JUICE_TRAP")
    conf = confidence(m_pct, t_pct)
    edge = (conf - implied_prob(bet_price)) * 100.0
    trap = any(f in TRAP_FLAGS for f in flags)
    tier, units = tier_and_units(money_pct=m_pct, conf=conf, edge=edge, trap=trap)
    return {
        "market": market,
        "line": bet_line,
        "price": bet_price,
        "price_estimated": price_estimated,
        "money_pct": m_pct,
        "ticket_pct": t_pct,
        "conf": round(conf, 4),
        "edge": round(edge, 2),
        "flags": flags,
        "tier": tier,
        "units": units,
    }


def _book_offer(event: dict[str, Any] | None, market: str, side: str) -> dict[str, Any] | None:
    books = (event or {}).get("bookmakers") or {}
    for b in SOURCE_BOOKS:
        bm = books.get(b)
        if not bm:
            continue
        for o in (bm.get("markets") or {}).get(market) or []:
            if o.get("side") == side and o.get("price") is not None:
                if market == "spreads" and o.get("point") is None:
                    continue
                return {
                    "book": b,
                    "price": float(o["price"]),
                    "line": float(o["point"]) if o.get("point") is not None else None,
                }
    return None


def evaluate(
    game: dict[str, Any],
    splits: dict[str, Any] | None,
    event: dict[str, Any] | None,
    *,
    is_mid_major_by_side: dict[str, bool],
    ratings: dict[str, dict[str, float]] | None = None,
    ratings_provenance: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate one game. ``event`` (Odds API) may be None: AN consensus line is used then."""
    base = {
        "engine": ENGINE,
        "espn_id": str(game.get("espn_id") or ""),
        "home_team": game.get("home_team"),
        "away_team": game.get("away_team"),
    }
    sp = (splits or {}).get("spread") or {}
    h, a = sp.get("home") or {}, sp.get("away") or {}
    if not has_splits(splits):
        return {**base, "result": "no_splits", "reason": "No splits data"}
    gaps = {
        "home": float(h["money_pct"]) - float(h["ticket_pct"]),
        "away": float(a["money_pct"]) - float(a["ticket_pct"]),
    }
    pos = [s for s in ("home", "away") if gaps[s] > 0]
    if not pos:
        return {**base, "result": "warning", "reason": "No sharp gap"}
    side = max(pos, key=lambda s: gaps[s])
    sd = sp[side]
    offer = _book_offer(event, "spreads", side)
    ml_offer = _book_offer(event, "h2h", side)
    if offer:
        line, price, book, source = offer["line"], offer["price"], offer["book"], "odds_api"
    elif sd.get("line") is not None and sd.get("price") is not None:
        line, price, book, source = float(sd["line"]), float(sd["price"]), "actionnetwork", "actionnetwork"
    else:
        return {**base, "result": "warning", "reason": "No line", "side": side, "gap": gaps[side]}
    ml_price = ml_offer["price"] if ml_offer else (((splits or {}).get("ml") or {}).get(side) or {}).get("price")
    mls = ((splits or {}).get("ml") or {}).get(side) or {}
    neutral = bool(game.get("neutral_site"))
    res = logic_gates(
        line=line,
        price=price,
        money_pct=float(sd["money_pct"]),
        ticket_pct=float(sd["ticket_pct"]),
        is_mid_major=bool(is_mid_major_by_side.get(side, True)),
        is_road=(side == "away" and not neutral),
        ml_price=float(ml_price) if ml_price is not None else None,
        ml_money_pct=mls.get("money_pct"),
        ml_ticket_pct=mls.get("ticket_pct"),
    )
    if res["market"] == "h2h" and ml_offer:
        book = ml_offer["book"]
    out = {
        **base,
        **res,
        "side": side,
        "gap": round(gaps[side], 2),
        "book": book,
        "line_source": source,
        "orig_line": line,
        "orig_price": price,
        "splits_source": (splits or {}).get("splits_source"),
        "result": "trap" if res["tier"] == "TRAP" else "play",
    }
    sim = monte_carlo_projection(
        game,
        side=side,
        market=str(res.get("market") or "spreads"),
        line=res.get("line"),
        ratings=ratings,
        ratings_provenance=ratings_provenance,
        now=now,
    )
    out["sim_projection"] = sim
    out["sim_rec"] = format_sim_rec(sim)
    if out["result"] == "trap":
        out["reason"] = ", ".join(f for f in res["flags"] if f in TRAP_FLAGS)
    return out
