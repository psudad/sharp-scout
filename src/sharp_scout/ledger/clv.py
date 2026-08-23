"""Closing Line Value (CLV) — did we beat the number the market closed at?

CLV is the earliest statistically meaningful proof that a process has real edge — it
converges far faster than win/loss. We track it two ways per play:

* ``clv_points`` — points gained vs the closing line (side-adjusted). For a spread bet on
  the home team at -2.5 that closed at -4, we gained +1.5 points. For totals, an Over bet
  gains points when the total closes higher; an Under gains when it closes lower. Moneyline
  has no line, so ``clv_points`` is ``None``.
* ``clv_prob`` — no-vig-free implied-probability gain on our side: ``p_close - p_bet`` using
  American prices. Positive means the closing price implied our side was *more* likely than
  the price we took (i.e. we bought low).

Closing lines are sourced from :mod:`sharp_scout.data.line_store` (the timestamped sharp
line history), taking the last sample at/before kickoff.
"""

from __future__ import annotations

import logging
from typing import Any

from sharp_scout.data import line_store
from sharp_scout.utils.odds import american_to_implied_prob

logger = logging.getLogger(__name__)

CLV_FIELDS = ("close_line", "close_price", "close_book", "clv_points", "clv_prob", "clv_at")


def clv_points(market: str | None, side: str | None, bet_line: Any, close_line: Any) -> float | None:
    """Points of closing-line value on our side (positive = we beat the close)."""
    if bet_line is None or close_line is None:
        return None
    try:
        bet = float(bet_line)
        close = float(close_line)
    except (TypeError, ValueError):
        return None

    s = str(side or "").lower()
    if market == "spreads":
        # Lines stored per side (e.g. away -2.5). Getting more points is favorable:
        # our number should be higher (less negative / more positive) than the close.
        return round(bet - close, 2)
    if market == "totals":
        if s == "over":
            # Over is better when it closed lower than our line (we took the lower total).
            return round(close - bet, 2)
        if s == "under":
            # Under is better when it closed higher than our line.
            return round(bet - close, 2)
    return None


def clv_prob(bet_price: Any, close_price: Any) -> float | None:
    """Implied-probability gain on our side from bet price → closing price."""
    if bet_price is None or close_price is None:
        return None
    try:
        p_bet = american_to_implied_prob(float(bet_price))
        p_close = american_to_implied_prob(float(close_price))
    except (TypeError, ValueError):
        return None
    return round(p_close - p_bet, 4)


def compute_clv_for_play(
    play: dict[str, Any],
    close_line: Any,
    close_price: Any,
    *,
    close_book: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Attach CLV fields to a play in place and return it."""
    from datetime import datetime, timezone

    market = play.get("market")
    side = play.get("side")
    play["close_line"] = float(close_line) if close_line is not None else None
    play["close_price"] = float(close_price) if close_price is not None else None
    play["close_book"] = close_book
    play["clv_points"] = clv_points(market, side, play.get("line"), close_line)
    play["clv_prob"] = clv_prob(play.get("price"), close_price)
    play["clv_at"] = at or datetime.now(timezone.utc).isoformat()
    return play


def _needs_clv(play: dict[str, Any]) -> bool:
    if play.get("play_type") == "prop" or str(play.get("market") or "").startswith("player_"):
        return False  # props priced off usage, not a comparable sharp closing side
    return play.get("clv_at") is None


def finalize_closing_lines(
    ledger: dict[str, Any],
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
    history_path: Any = None,
) -> int:
    """Fill CLV on plays whose closing line is now available in the line store.

    Returns the number of plays updated. Safe to call repeatedly (idempotent per play).
    """
    hist = history if history is not None else line_store.load_history(history_path)
    updated = 0
    for play in ledger.get("plays") or []:
        if not _needs_clv(play):
            continue
        close = line_store.closing_sample(
            play.get("event_id"),
            str(play.get("market")),
            str(play.get("side")),
            kickoff=play.get("kickoff"),
            history=hist,
        )
        if not close:
            continue
        compute_clv_for_play(
            play,
            close.get("line"),
            close.get("price"),
            close_book=close.get("book"),
            at=close.get("ts"),
        )
        updated += 1
    if updated:
        logger.info("CLV: finalized closing lines for %d plays", updated)
    return updated


def summarize_clv(ledger: dict[str, Any]) -> dict[str, Any]:
    """Aggregate CLV across plays that have a recorded closing line."""
    plays = [p for p in (ledger.get("plays") or []) if p.get("clv_at")]
    pts = [p["clv_points"] for p in plays if p.get("clv_points") is not None]
    probs = [p["clv_prob"] for p in plays if p.get("clv_prob") is not None]
    beat = sum(1 for x in probs if x > 0)
    n_prob = len(probs)
    return {
        "n_plays_with_clv": len(plays),
        "avg_clv_points": round(sum(pts) / len(pts), 3) if pts else None,
        "avg_clv_prob": round(sum(probs) / n_prob, 4) if n_prob else None,
        "beat_close_pct": round(beat / n_prob, 3) if n_prob else None,
        "beat_close_record": f"{beat}-{n_prob - beat}" if n_prob else None,
    }
