"""Extract consensus / Pinnacle lines from an in-memory Odds API event (no extra calls)."""

from __future__ import annotations

from statistics import median
from typing import Any

from sharp_scout.nba.fair import consensus_two_way_fair, sharp_two_way_fair

# Pace-of-play gap is measured vs this line; drop books far from the sharp anchor.
_CONSENSUS_OUTLIER_PTS = 2.0
_SHARP_BOOK_ORDER = ("pinnacle", "circa", "circa_sports", "betfair_ex_eu")


def _home_spread_from_outcomes(outcomes: list[dict[str, Any]]) -> float | None:
    for o in outcomes:
        if str(o.get("side") or "").lower() == "home" and o.get("point") is not None:
            return float(o["point"])
    return None


def _total_line_from_outcomes(outcomes: list[dict[str, Any]]) -> float | None:
    for o in outcomes:
        side = str(o.get("side") or "").lower()
        if side == "over" and o.get("point") is not None:
            return float(o["point"])
    return None


def _book_spread_home(books: dict[str, Any], book_key: str) -> float | None:
    bm = books.get(book_key) or {}
    outcomes = (bm.get("markets") or {}).get("spreads") or []
    return _home_spread_from_outcomes(outcomes)


def _book_total(books: dict[str, Any], book_key: str) -> float | None:
    bm = books.get(book_key) or {}
    outcomes = (bm.get("markets") or {}).get("totals") or []
    return _total_line_from_outcomes(outcomes)


def _collect_book_points(books: dict[str, Any], market: str, *, side: str) -> dict[str, float]:
    out: dict[str, float] = {}
    side_l = side.lower()
    for book_key, bm in books.items():
        for o in (bm.get("markets") or {}).get(market) or []:
            if str(o.get("side") or "").lower() == side_l and o.get("point") is not None:
                out[str(book_key)] = float(o["point"])
                break
    return out


def _sharp_anchor_point(books: dict[str, Any], market: str, *, side: str) -> float | None:
    by_book = _collect_book_points(books, market, side=side)
    for key in _SHARP_BOOK_ORDER:
        if key in by_book:
            return by_book[key]
    for key, bm in books.items():
        if bm.get("is_sharp") and key in by_book:
            return by_book[key]
    return None


def robust_consensus_point(
    event: dict[str, Any],
    market: str,
    *,
    side: str,
    outlier_pts: float = _CONSENSUS_OUTLIER_PTS,
) -> float | None:
    """Median line across books, anchored to Pinnacle/sharp and with outlier books dropped."""
    books = event.get("bookmakers") or {}
    by_book = _collect_book_points(books, market, side=side)
    if not by_book:
        return None
    pts = list(by_book.values())
    anchor = _sharp_anchor_point(books, market, side=side)
    if anchor is None:
        anchor = float(median(pts))
    filtered = [p for p in pts if abs(p - anchor) <= outlier_pts]
    if not filtered:
        return float(anchor)
    if len(filtered) == 1:
        return filtered[0]
    return float(median(filtered))


def _consensus_line(event: dict[str, Any], market: str, *, side_key: str) -> float | None:
    point = robust_consensus_point(event, market, side=side_key)
    if point is not None:
        return point
    ref = consensus_two_way_fair(event, market, min_books=2)
    if not ref:
        return None
    for o in ref.get("outcomes") or []:
        if str(o.get("side") or "").lower() == side_key and o.get("point") is not None:
            return float(o["point"])
    return robust_consensus_point(event, market, side=side_key)


def _consensus_median_point(event: dict[str, Any], market: str, side: str) -> float | None:
    return robust_consensus_point(event, market, side=side)


def snapshot_game_lines(event: dict[str, Any]) -> dict[str, float | None]:
    """Home spread (home line) and total (over line) for consensus + Pinnacle."""
    books = event.get("bookmakers") or {}
    sharp = sharp_two_way_fair(event, "spreads")
    pin_spread = _book_spread_home(books, "pinnacle")
    pin_total = _book_total(books, "pinnacle")
    if pin_spread is None and sharp:
        pin_spread = _home_spread_from_outcomes(sharp.get("outcomes") or [])
    sharp_t = sharp_two_way_fair(event, "totals")
    if pin_total is None and sharp_t:
        pin_total = _total_line_from_outcomes(sharp_t.get("outcomes") or [])
    return {
        "consensus_spread_home": _consensus_line(event, "spreads", side_key="home"),
        "consensus_total": _consensus_line(event, "totals", side_key="over"),
        "pinnacle_spread_home": pin_spread,
        "pinnacle_total": pin_total,
    }
