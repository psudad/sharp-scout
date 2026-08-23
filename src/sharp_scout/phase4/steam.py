"""Steam detection — sharp line velocity across books.

Steam is a line that moves sharply across *many* sharp books within a short window (e.g.
-2 to -3 across every book in minutes), as opposed to drifting over many hours. It is a
distinct confirmation from RLM: RLM is *direction vs. the public*, steam is *velocity and
breadth across sharp books*.

We compute, per event/market/side, over a look-back window:

    steam_score = magnitude × speed_factor × n_books_moving × confirmation

* ``magnitude`` — median favorable line move (points) toward our side across books.
* ``speed_factor`` — how fast it moved (points/hour, capped) — fast moves score higher.
* ``n_books_moving`` — count of sharp books that moved ≥ one tick toward our side.
* ``confirmation`` — fraction of moving books that agreed on direction (0–1).

Data comes from :mod:`sharp_scout.data.line_store` (timestamped sharp line history).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.data import line_store

logger = logging.getLogger(__name__)

_TICK = 0.5  # minimum meaningful line move (points)


def _parse_ts(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _favorable_move(market: str, side: str, first_line: float, last_line: float) -> float:
    """Points the line moved toward our side (positive = market agrees with us)."""
    if market == "spreads":
        # Each side's own point: moving more negative = toward that side.
        return first_line - last_line
    if market == "totals":
        s = str(side).lower()
        if s == "over":
            return last_line - first_line  # total rising → toward over
        if s == "under":
            return first_line - last_line  # total falling → toward under
    return 0.0


def _book_moves(
    samples: list[dict[str, Any]],
    market: str,
    side: str,
    window_start: datetime,
) -> dict[str, float]:
    """Per-book favorable move within the window (needs a line, so h2h is skipped)."""
    by_book: dict[str, list[dict[str, Any]]] = {}
    for s in samples:
        ts = _parse_ts(s.get("ts"))
        if ts is None or ts < window_start:
            continue
        if s.get("line") is None:
            continue
        by_book.setdefault(str(s.get("book")), []).append({**s, "_ts": ts})

    moves: dict[str, float] = {}
    for book, series in by_book.items():
        series.sort(key=lambda x: x["_ts"])
        if len(series) < 2:
            continue
        first = float(series[0]["line"])
        last = float(series[-1]["line"])
        moves[book] = _favorable_move(market, side, first, last)
    return moves


def steam_signal(
    event_id: Any,
    market: str,
    side: str,
    *,
    now: datetime | None = None,
    window_minutes: int | None = None,
    history: dict[str, list[dict[str, Any]]] | None = None,
    history_path: Any = None,
) -> dict[str, Any]:
    """Return steam metrics for one event/market/side."""
    settings = get_settings()
    win = window_minutes if window_minutes is not None else settings.steam_window_minutes
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=win)

    result = {
        "steam": False,
        "score": 0.0,
        "magnitude": 0.0,
        "speed": 0.0,
        "n_books": 0,
        "confirmation": 0.0,
        "note": "no line history",
    }
    if market not in ("spreads", "totals"):
        result["note"] = "steam only applies to spreads/totals"
        return result

    samples = line_store.samples_for(event_id, market, side, path=history_path, history=history)
    if not samples:
        return result

    moves = _book_moves(samples, market, side, window_start)
    if not moves:
        result["note"] = "no book moved within window"
        return result

    favorable = [m for m in moves.values() if m >= _TICK]
    against = [m for m in moves.values() if m <= -_TICK]
    n_moving = len(favorable) + len(against)
    n_books = len(favorable)
    if n_books == 0:
        result["note"] = "line moved against our side" if against else "flat"
        result["n_books"] = 0
        return result

    favorable.sort()
    magnitude = favorable[len(favorable) // 2]  # median favorable move (points)
    confirmation = n_books / n_moving if n_moving else 0.0

    # Speed: median move over the observed span (points/hour), capped.
    span_hours = max(win / 60.0, 1e-3)
    speed = magnitude / span_hours
    speed_factor = min(1.0 + speed, 4.0)  # emphasize fast moves, cap runaway values

    score = magnitude * speed_factor * n_books * confirmation

    detected = (
        score >= settings.steam_score_threshold
        and n_books >= settings.steam_min_books
        and magnitude >= settings.steam_min_points
    )
    result.update(
        {
            "steam": bool(detected),
            "score": round(score, 3),
            "magnitude": round(magnitude, 2),
            "speed": round(speed, 3),
            "n_books": n_books,
            "confirmation": round(confirmation, 2),
            "note": (
                f"steam: {n_books} sharp books moved ~{magnitude:g}pt toward {side} "
                f"(score {score:.2f})"
                if detected
                else f"{n_books} book(s) moved {magnitude:g}pt toward {side}, below steam threshold"
            ),
        }
    )
    return result
