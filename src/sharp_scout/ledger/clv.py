"""Closing Line Value (CLV) — did we beat the number the market closed at?

CLV is the earliest statistically meaningful proof that a process has real edge — it
converges far faster than win/loss. We track it two ways per play:

* ``clv_points`` — points gained vs the closing line (side-adjusted). For a spread bet on
  the home team at -2.5 that closed at -4, we gained +1.5 points. For totals, an Over bet
  gains points when the total closes higher; an Under gains when it closes lower. Moneyline
  has no line, so ``clv_points`` is ``None``.
* ``clv_prob`` — no-vig implied-probability gain on our side at the **same line** as our
  bet: ``p_close - p_bet`` using American prices from the closing sample. When our bet line
  differs from the sharp closing line, ``clv_prob`` is omitted and ``clv_basis`` is
  ``points`` so headline beat-close stats use point CLV instead of a mismatched price compare.

Closing lines are sourced from :mod:`sharp_scout.data.line_store` (the timestamped sharp
line history), taking the last Pinnacle-preferred sample at/before kickoff, refreshed on
each scan until kickoff then frozen.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sharp_scout.data import line_store
from sharp_scout.utils.odds import american_to_implied_prob

logger = logging.getLogger(__name__)

CLV_FIELDS = (
    "close_line",
    "close_price",
    "close_book",
    "clv_points",
    "clv_prob",
    "clv_basis",
    "clv_at",
)


def _lines_match(bet_line: Any, close_line: Any) -> bool:
    if bet_line is None and close_line is None:
        return True
    if bet_line is None or close_line is None:
        return False
    try:
        return abs(float(bet_line) - float(close_line)) < 1e-6
    except (TypeError, ValueError):
        return False


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
    """Implied-probability gain on our side from bet price → closing price (same line)."""
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
    market = play.get("market")
    side = play.get("side")
    play["close_line"] = float(close_line) if close_line is not None else None
    play["close_price"] = float(close_price) if close_price is not None else None
    play["close_book"] = close_book
    play["clv_points"] = clv_points(market, side, play.get("line"), close_line)

    same_line = market == "h2h" or _lines_match(play.get("line"), close_line)
    if same_line:
        play["clv_prob"] = clv_prob(play.get("price"), close_price)
        play["clv_basis"] = "prob" if play["clv_prob"] is not None else None
    else:
        play["clv_prob"] = None
        play["clv_basis"] = "points" if play["clv_points"] is not None else None

    play["clv_at"] = at or datetime.now(timezone.utc).isoformat()
    return play


def _play_eligible_for_clv(play: dict[str, Any]) -> bool:
    if play.get("play_type") == "prop" or str(play.get("market") or "").startswith("player_"):
        return False
    return True


def _should_refresh_clv(play: dict[str, Any], close: dict[str, Any], *, now: datetime) -> bool:
    """Refresh until kickoff while newer pre-kick samples arrive; re-open if stored close was stale."""
    close_ts = str(close.get("ts") or "")
    stored_ts = str(play.get("clv_at") or "")
    if not stored_ts:
        return True

    ko = line_store._parse_ts(play.get("kickoff"))
    if ko is not None and now > ko:
        return (
            close_ts != stored_ts
            or play.get("close_line") != close.get("line")
            or play.get("close_price") != close.get("price")
            or play.get("close_book") != close.get("book")
        )

    return close_ts > stored_ts


def _beat_close_value(play: dict[str, Any]) -> float | None:
    if play.get("clv_prob") is not None:
        return float(play["clv_prob"])
    if play.get("clv_points") is not None:
        return float(play["clv_points"])
    return None


def finalize_closing_lines(
    ledger: dict[str, Any],
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
    history_path: Any = None,
    now: datetime | None = None,
    force: bool = False,
) -> int:
    """Fill or refresh CLV from the line store (last sharp sample at/before kickoff).

    Returns the number of plays updated. Before kickoff, each call may advance the stored
    close as new snapshots arrive. After kickoff, updates only when the canonical close
    differs from what was stored (e.g. early snapshot bug or backfill).
    """
    hist = history if history is not None else line_store.load_history(history_path)
    clock = now or datetime.now(timezone.utc)
    updated = 0
    for play in ledger.get("plays") or []:
        if not _play_eligible_for_clv(play):
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
        if not force and not _should_refresh_clv(play, close, now=clock):
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
        logger.info("CLV: refreshed closing lines for %d plays", updated)
    return updated


def refresh_ledger_closing_lines(path: Any = None, *, force: bool = False) -> int:
    """Load ledger, refresh CLV, save if anything changed."""
    from sharp_scout.ledger.tracker import load_ledger, save_ledger

    ledger = load_ledger(path)
    n = finalize_closing_lines(ledger, force=force)
    if n:
        save_ledger(ledger, path)
    return n


def summarize_clv(ledger: dict[str, Any]) -> dict[str, Any]:
    """Aggregate CLV across plays that have a recorded closing line."""
    plays = [p for p in (ledger.get("plays") or []) if p.get("clv_at")]
    pts = [p["clv_points"] for p in plays if p.get("clv_points") is not None]
    probs = [p["clv_prob"] for p in plays if p.get("clv_prob") is not None]
    beat_vals = [_beat_close_value(p) for p in plays]
    beat_vals = [v for v in beat_vals if v is not None]
    beat = sum(1 for x in beat_vals if x > 0)
    n_beat = len(beat_vals)
    n_prob = len(probs)
    return {
        "n_plays_with_clv": len(plays),
        "avg_clv_points": round(sum(pts) / len(pts), 3) if pts else None,
        "avg_clv_prob": round(sum(probs) / n_prob, 4) if n_prob else None,
        "beat_close_pct": round(beat / n_beat, 3) if n_beat else None,
        "beat_close_record": f"{beat}-{n_beat - beat}" if n_beat else None,
        "n_beat_close": n_beat,
        "n_clv_prob": n_prob,
        "n_clv_points": len(pts),
    }


def summarize_clv_by_market(ledger: dict[str, Any]) -> dict[str, Any]:
    """Season CLV split for spreads vs totals (and h2h when present)."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for p in ledger.get("plays") or []:
        if not p.get("clv_at"):
            continue
        m = str(p.get("market") or "unknown")
        buckets.setdefault(m, []).append(p)
    return {m: summarize_clv({"plays": rows}) for m, rows in sorted(buckets.items())}
