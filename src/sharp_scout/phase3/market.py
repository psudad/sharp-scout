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
    p_model: float | None = None  # raw sim probability before market anchoring
    p_fair: float | None = None  # sharp no-vig shifted to the offered line
    line_gain: float | None = None  # points of line advantage vs the sharp book (+ = better)


def shift_prob_to_line(
    p_at_ref: float,
    *,
    market: str,
    side: str,
    ref_line: float | None,
    line: float | None,
    sd: float,
) -> tuple[float, float]:
    """Move a cover/over probability from the sharp book's line to the offered line.

    Uses a normal margin/total with the sport's calibrated sd. Returns (p, line_gain)
    where line_gain is the points of advantage for `side` (positive = better number).
    """
    if market == "h2h" or ref_line is None or line is None:
        return p_at_ref, 0.0
    if market == "spreads":
        gain = float(line) - float(ref_line)  # +7.5 offered vs +6.5 sharp → +1
    elif side == "over":
        gain = float(ref_line) - float(line)
    else:
        gain = float(line) - float(ref_line)
    from scipy.stats import norm

    z = norm.ppf(min(max(p_at_ref, 0.02), 0.98)) + gain / max(sd, 1.0)
    return float(norm.cdf(z)), gain


def anchor_probability(p_model: float, p_fair: float | None, k: float) -> float:
    """p_true = p_fair + k·(p_model − p_fair); model-only when no sharp reference."""
    if p_fair is None:
        return p_model
    return float(min(max(p_fair + k * (p_model - p_fair), 0.001), 0.999))


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
    calibrate: Any = None,
    sport: str | None = None,
) -> list[EdgeCandidate]:
    """Price every book/side against a market-anchored probability.

    Backtests (546 NFL games 2024–26, 259 CFB games 2026) show the EPA model does not
    beat the closing line on its own (NFL 48.7%, CFB 46%), so the sharp book's no-vig
    price — shifted to the offered line — is the anchor and the model is a tilt:
    ``p_true = p_fair + k·(p_model − p_fair)``. Edge then comes from (a) a better
    number/price than the sharp book and (b) a bounded model opinion.
    """
    settings = get_settings()
    thr = settings.ev_threshold if ev_threshold is None else ev_threshold
    edges: list[EdgeCandidate] = []
    books = event.get("bookmakers", {})
    cfg = None
    if sport:
        from sharp_scout.sports import get_sport

        cfg = get_sport(sport)

    for market in ("spreads", "totals", "h2h"):
        sharp = sharp_consensus(event, market)
        sharp_map: dict[str, dict] = {}
        if sharp:
            for o in sharp["outcomes"]:
                sharp_map[o["side"]] = o
        if cfg is None:
            k_anchor = 1.0
            sd = 13.5
        else:
            k_anchor = {
                "spreads": cfg.anchor_k_spread,
                "totals": cfg.anchor_k_total,
                "h2h": cfg.anchor_k_ml,
            }[market]
            sd = cfg.margin_sd if market == "spreads" else cfg.total_sd

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

                # Apply probability calibration (identity until a calibrator is fit).
                if calibrate is not None:
                    try:
                        p_true = float(calibrate(p_true))
                    except Exception:  # noqa: BLE001
                        pass

                # Sharp no-vig at the sharp book's line → shifted to this book's line.
                p_model = p_true
                p_mkt = None
                p_fair = None
                line_gain = None
                sharp_price = None
                sharp_book = None
                if side in sharp_map:
                    p_ref = sharp_map[side].get("p_mkt")
                    sharp_price = sharp_map[side].get("price")
                    sharp_book = sharp["book"] if sharp else None
                    if p_ref is not None:
                        p_fair, line_gain = shift_prob_to_line(
                            float(p_ref),
                            market=market,
                            side=side,
                            ref_line=sharp_map[side].get("point"),
                            line=line,
                            sd=sd,
                        )
                        p_mkt = p_fair
                elif side in local_fair:
                    p_mkt = local_fair[side]
                    # Own-book no-vig is not a sharp reference: anchor to it only
                    # when we would otherwise be model-only (k=1 means no anchoring).
                    p_fair = p_mkt if k_anchor < 1.0 else None

                if k_anchor < 1.0:
                    p_true = anchor_probability(p_model, p_fair, k_anchor)

                edge = expected_value(p_true, float(price))
                if k_anchor < 1.0:
                    # Anchored: EV already embeds the sharp reference (line gain + tilt).
                    # Only require that the model does not lean against the play.
                    ok_dev = p_fair is None or p_model >= p_fair - 0.01
                else:
                    # Model-only: require a meaningful deviation from the sharp reference.
                    ok_dev = (abs(p_true - p_mkt) if p_mkt is not None else 1.0) >= 0.01
                if edge >= thr and ok_dev:
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
                            p_model=round(float(p_model), 4),
                            p_fair=round(float(p_fair), 4) if p_fair is not None else None,
                            line_gain=line_gain,
                        )
                    )
    edges.sort(key=lambda e: e.edge, reverse=True)
    return edges