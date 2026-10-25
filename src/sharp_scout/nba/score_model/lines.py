"""Extract consensus / Pinnacle lines from an in-memory Odds API event (no extra calls)."""

from __future__ import annotations

from statistics import median
from typing import Any

from sharp_scout.nba.fair import consensus_two_way_fair, sharp_two_way_fair


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


def _consensus_line(event: dict[str, Any], market: str, *, side_key: str) -> float | None:
    ref = consensus_two_way_fair(event, market, min_books=2)
    if not ref:
        return None
    for o in ref.get("outcomes") or []:
        if str(o.get("side") or "").lower() == side_key and o.get("point") is not None:
            return float(o["point"])
    if market == "spreads":
        return _consensus_median_point(event, market, "home")
    if market == "totals":
        return _consensus_median_point(event, market, "over")
    return None


def _consensus_median_point(event: dict[str, Any], market: str, side: str) -> float | None:
    books = event.get("bookmakers") or {}
    pts: list[float] = []
    for bm in books.values():
        for o in (bm.get("markets") or {}).get(market) or []:
            if str(o.get("side") or "").lower() == side and o.get("point") is not None:
                pts.append(float(o["point"]))
    return float(median(pts)) if pts else None


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
