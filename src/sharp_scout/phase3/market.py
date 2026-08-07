"""Phase 3 — No-vig market probabilities and EV / mispricing discovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.phase2.monte_carlo import GameSimResult, p_true_for_market
from sharp_scout.utils.odds import american_to_implied_prob, expected_value

logger = logging.getLogger(__name__)


@dataclass
class EdgeCandidate:
    event_id: str
    home_team: str
    away_team: str
    market: str
    side: str
    line: float | None
    book: str
    price: float
    p_true: float
    p_mkt: float | None
    edge: float
    sharp_book: str | None
    sharp_price: float | None
    model_spread: float
    model_total: float


def multiplicative_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    s = prob_a + prob_b
    if s <= 0:
        return 0.5, 0.5
    return prob_a / s, prob_b / s


def power_devig(prob_a: float, prob_b: float, tol: float = 1e-8) -> tuple[float, float]:
    """Shin/power-style: find k such that p_i^k sums to 1."""
    # Binary search k
    lo, hi = 0.5, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        s = prob_a**mid + prob_b**mid
        if s > 1:
            lo = mid
        else:
            hi = mid
        if abs(s - 1) < tol:
            break
    k = (lo + hi) / 2
    pa, pb = prob_a**k, prob_b**k
    z = pa + pb
    return pa / z, pb / z


def fair_probs_from_two_way(
    price_a: float,
    price_b: float,
    method: str = "multiplicative",
) -> tuple[float, float]:
    ia = american_to_implied_prob(price_a)
    ib = american_to_implied_prob(price_b)
    if method == "power":
        return power_devig(ia, ib)
    return multiplicative_devig(ia, ib)


def sharp_consensus(
    event: dict[str, Any],
    market: str,
) -> dict[str, Any] | None:
    """Build no-vig consensus from preferred sharp book for a market."""
    books = event.get("bookmakers", {})
    preference = ["pinnacle", "circa", "circa_sports", "betfair_ex_eu"]
    chosen = None
    for key in preference:
        if key in books and market in books[key].get("markets", {}):
            chosen = (key, books[key]["markets"][market])
            break
    if chosen is None:
        for key, bm in books.items():
            if bm.get("is_sharp") and market in bm.get("markets", {}):
                chosen = (key, bm["markets"][market])
                break
    if chosen is None:
        return None

    book, outcomes = chosen
    if len(outcomes) < 2:
        return None
    a, b = outcomes[0], outcomes[1]
    if a.get("price") is None or b.get("price") is None:
        return None
    pa, pb = fair_probs_from_two_way(float(a["price"]), float(b["price"]))
    return {
        "book": book,
        "outcomes": [
            {**a, "p_mkt": pa},
            {**b, "p_mkt": pb},
        ],
        "line": a.get("point"),
    }


def discover_edges(
    event: dict[str, Any],
    sim: GameSimResult,
    ev_threshold: float | None = None,
) -> list[EdgeCandidate]:
    settings = get_settings()
    thr = settings.ev_threshold if ev_threshold is None else ev_threshold
    edges: list[EdgeCandidate] = []
    books = event.get("bookmakers", {})

    for market in ("spreads", "totals", "h2h"):
        sharp = sharp_consensus(event, market)
        sharp_map: dict[str, dict] = {}
        if sharp:
            for o in sharp["outcomes"]:
                sharp_map[o["side"]] = o

        for book_key, bm in books.items():
            mkts = bm.get("markets", {})
            if market not in mkts:
                continue
            outcomes = mkts[market]
            # Pair for market fair probs on this book (for reporting)
            if len(outcomes) >= 2 and outcomes[0].get("price") and outcomes[1].get("price"):
                fair_a, fair_b = fair_probs_from_two_way(
                    float(outcomes[0]["price"]), float(outcomes[1]["price"])
                )
                local_fair = {outcomes[0]["side"]: fair_a, outcomes[1]["side"]: fair_b}
            else:
                local_fair = {}

            for o in outcomes:
                price = o.get("price")
                if price is None:
                    continue
                side = o["side"]
                line = o.get("point")
                try:
                    p_true = p_true_for_market(sim, market, side, line)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("p_true skip %s: %s", o, exc)
                    continue

                # Prefer sharp no-vig as P_mkt reference; else this book's no-vig
                p_mkt = None
                sharp_price = None
                sharp_book = None
                if side in sharp_map:
                    p_mkt = sharp_map[side].get("p_mkt")
                    sharp_price = sharp_map[side].get("price")
                    sharp_book = sharp["book"] if sharp else None
                elif side in local_fair:
                    p_mkt = local_fair[side]

                edge = expected_value(p_true, float(price))
                # Also require meaningful deviation from sharp consensus when available
                vs_mkt = abs(p_true - p_mkt) if p_mkt is not None else 1.0
                if edge >= thr and vs_mkt >= 0.01:
                    edges.append(
                        EdgeCandidate(
                            event_id=str(event.get("event_id")),
                            home_team=event["home_team"],
                            away_team=event["away_team"],
                            market=market,
                            side=side,
                            line=float(line) if line is not None else None,
                            book=book_key,
                            price=float(price),
                            p_true=p_true,
                            p_mkt=p_mkt,
                            edge=edge,
                            sharp_book=sharp_book,
                            sharp_price=float(sharp_price) if sharp_price is not None else None,
                            model_spread=sim.model_spread,
                            model_total=sim.model_total,
                        )
                    )
    edges.sort(key=lambda e: e.edge, reverse=True)
    return edges