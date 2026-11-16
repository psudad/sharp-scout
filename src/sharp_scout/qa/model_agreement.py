"""Certification gate: official plays must align with the model's own lean.

Blocks when raw model probability on our side is below break-even at the bet price,
or when the model's projected margin / total points the other way.
"""

from __future__ import annotations

import statistics
from typing import Any

from sharp_scout.utils.odds import american_to_implied_prob, expected_value, expected_value_with_push


def break_even_win_prob(price: float, *, p_push: float = 0.0) -> float:
    """Implied win/cover probability at which EV is zero (marginal, with push)."""
    be = american_to_implied_prob(float(price))
    if p_push > 0:
        # EV=0: p_cond * dec - (1-p_cond - p_push) = 0 with push refund
        dec = 1 + price / 100.0 if price > 0 else 1 + 100.0 / abs(price)
        return (1.0 + p_push) / dec
    return be


def model_margin_disagrees(play: dict[str, Any]) -> tuple[bool, str | None]:
    """Mean margin/total leans the wrong way (independent of market anchor)."""
    mm = play.get("model_margin")
    if mm is None:
        return False, None
    margin = float(mm)
    side = str(play.get("side") or "")
    market = str(play.get("market") or "")
    if market == "h2h":
        if side == "home" and margin <= 0:
            return True, f"model mean margin {margin:+.1f} — home not favored to win"
        if side == "away" and margin >= 0:
            return True, f"model mean margin {margin:+.1f} — away not favored to win"
        return False, None
    # Spreads: rely on p_model vs break-even — mean margin can favor a dog while MC cover prob does not.
    if market == "totals":
        mt = play.get("model_total")
        line = play.get("line")
        if mt is None or line is None:
            return False, None
        total = float(mt)
        ln = float(line)
        if side == "over" and total <= ln:
            return True, f"model total {total:.1f} ≤ line {ln:g}"
        if side == "under" and total >= ln:
            return True, f"model total {total:.1f} ≥ line {ln:g}"
    return False, None


def model_probability_disagrees(play: dict[str, Any]) -> tuple[bool, str | None]:
    p_model = play.get("p_model")
    price = play.get("price")
    if p_model is None or price is None:
        return False, None
    p_push = float(play.get("p_push") or 0.0)
    be = break_even_win_prob(float(price), p_push=p_push)
    pm = float(p_model)
    if pm + 1e-9 < be:
        return (
            True,
            f"model {pm:.1%} on our side < {be:.1%} break-even at {float(price):+.0f}",
        )
    return False, None


def football_model_lean_from_signals(
    play: dict[str, Any], signals: dict[str, Any] | None
) -> dict[str, Any]:
    """Attach model_margin / model_total / p_model from a pipeline signal when missing."""
    merged = dict(play)
    if merged.get("p_model") is not None and merged.get("model_margin") is not None:
        return merged
    from sharp_scout.qa.product_gate import find_matching_signal

    sig = find_matching_signal(signals, play)
    if not sig:
        return merged
    for key in (
        "p_model",
        "model_margin",
        "model_total",
        "model_spread",
        "p_home_win",
    ):
        if merged.get(key) is None and sig.get(key) is not None:
            merged[key] = sig.get(key)
    if merged.get("model_margin") is None and merged.get("model_spread") is not None:
        merged["model_margin"] = -float(merged["model_spread"])
    if signals and merged.get("model_total") is None:
        eid = str(play.get("event_id") or "")
        if str(play.get("market")) == "totals":
            tr = (signals.get("nfl_totals_by_event") or {}).get(eid) or {}
            if tr.get("projection_total") is not None:
                merged["model_total"] = float(tr["projection_total"])
            elif tr.get("blended_total") is not None:
                merged["model_total"] = float(tr["blended_total"])
            elif sig and sig.get("model_total") is not None:
                merged["model_total"] = sig.get("model_total")
    if merged.get("p_model") is None and str(play.get("market")) == "h2h":
        ph = merged.get("p_home_win")
        side = str(play.get("side") or "")
        if ph is not None and side in ("home", "away"):
            merged["p_model"] = float(ph) if side == "home" else 1.0 - float(ph)
    return merged


def model_agreement_block_reason(
    play: dict[str, Any],
    *,
    signals: dict[str, Any] | None = None,
) -> str | None:
    row = football_model_lean_from_signals(play, signals) if signals else play
    for fn in (model_probability_disagrees, model_margin_disagrees):
        bad, reason = fn(row)
        if bad and reason:
            return reason
    return None


def one_book_outlier_block_reason(
    play: dict[str, Any],
    *,
    min_edge: float = 0.01,
    min_peer_books: int = 2,
    price_gap: float = 12.0,
) -> str | None:
    """Edge only at one outlier price vs peer books on the same side/line."""
    prices = play.get("peer_prices_at_line")
    if not isinstance(prices, list) or len(prices) < min_peer_books:
        return None
    p_fair = play.get("p_fair")
    if p_fair is None or play.get("price") is None:
        return None
    my_price = float(play["price"])
    try:
        median = statistics.median(float(x) for x in prices)
    except statistics.StatisticsError:
        return None
    if abs(my_price - median) < price_gap:
        return None
    p_push = float(play.get("p_push") or 0.0)
    pf = float(p_fair)
    mine_ev = (
        expected_value_with_push(pf, my_price, p_push)
        if p_push > 0
        else expected_value(pf, my_price)
    )
    med_ev = (
        expected_value_with_push(pf, median, p_push)
        if p_push > 0
        else expected_value(pf, median)
    )
    if mine_ev >= min_edge and med_ev < min_edge:
        book = play.get("book") or "book"
        return (
            f"one-book outlier: {book} {my_price:+.0f} vs peer median {median:+.0f} "
            f"(EV {mine_ev:.1%} vs {med_ev:.1%} at Pinnacle fair)"
        )
    return None


def model_agreement_and_outlier_reasons(
    play: dict[str, Any],
    *,
    signals: dict[str, Any] | None = None,
    outlier_min_edge: float = 0.01,
    outlier_price_gap: float = 12.0,
) -> tuple[str, ...]:
    reasons: list[str] = []
    agr = model_agreement_block_reason(play, signals=signals)
    if agr:
        reasons.append(f"model agreement: {agr}")
    out = one_book_outlier_block_reason(
        play, min_edge=outlier_min_edge, price_gap=outlier_price_gap
    )
    if out:
        reasons.append(out)
    return tuple(reasons)


def play_model_agrees(play: dict[str, Any], *, signals: dict[str, Any] | None = None) -> bool:
    return model_agreement_block_reason(play, signals=signals) is None