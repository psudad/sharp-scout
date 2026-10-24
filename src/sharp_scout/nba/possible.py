"""Near-miss NBA candidates for public display (not paper picks)."""

from __future__ import annotations

from typing import Any

from sharp_scout.config import get_settings

POSSIBLE_PICK_LIMIT = 15


def pick_dedupe_key(row: dict[str, Any]) -> tuple[Any, ...]:
    if (row.get("play_type") or "side") == "prop":
        return (
            str(row.get("event_id") or ""),
            str(row.get("player_name") or "").lower(),
            str(row.get("market") or ""),
            str(row.get("side") or "").lower(),
            float(row.get("line") or 0),
        )
    return (
        str(row.get("event_id") or ""),
        str(row.get("market") or ""),
        str(row.get("side") or "").lower(),
    )


def _book_rank(book: str | None) -> int:
    settings = get_settings()
    order = [settings.nba_primary_retail_book, settings.nba_secondary_retail_book]
    b = str(book or "").lower()
    try:
        return order.index(b)
    except ValueError:
        return len(order)


def finalize_possible_picks(
    candidates: list[dict[str, Any]],
    *,
    pick_keys: set[tuple[Any, ...]],
    limit: int = POSSIBLE_PICK_LIMIT,
) -> list[dict[str, Any]]:
    """Sort by EV, dedupe by market key (best edge; FanDuel on ties), cap list size."""
    pool: list[dict[str, Any]] = []
    for c in candidates:
        if float(c.get("edge") or 0) <= 0:
            continue
        key = pick_dedupe_key(c)
        if key in pick_keys:
            continue
        pool.append(c)

    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for c in pool:
        key = pick_dedupe_key(c)
        prev = best.get(key)
        if prev is None:
            best[key] = c
            continue
        ce = float(c.get("edge") or 0)
        pe = float(prev.get("edge") or 0)
        if ce > pe or (ce == pe and _book_rank(c.get("book")) < _book_rank(prev.get("book"))):
            best[key] = c

    ranked = sorted(best.values(), key=lambda x: float(x.get("edge") or 0), reverse=True)
    out: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        out.append(
            {
                **row,
                "units": 0,
                "tier": "watch",
                "pick_class": "possible",
                "display_only": True,
            }
        )
    return out


def split_possible_by_kind(
    possible: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sides = [p for p in possible if (p.get("play_type") or "side") != "prop"]
    props = [p for p in possible if (p.get("play_type") or "") == "prop"]
    return sides, props


def opportunity_row_to_signal(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a scan row into the shadow signal shape."""
    base = {
        "event_id": row.get("event_id"),
        "sport": "nba",
        "kickoff": row.get("kickoff"),
        "away_team": row.get("away_team"),
        "home_team": row.get("home_team"),
        "play_type": row.get("play_type") or "side",
        "market": row.get("market"),
        "side": row.get("side"),
        "line": row.get("line"),
        "book": row.get("book"),
        "price": row.get("price"),
        "units": row.get("units"),
        "tier": row.get("tier") or "paper",
        "edge": row.get("edge"),
        "p_true": row.get("p_true"),
        "p_mkt": row.get("p_mkt") or row.get("p_fair"),
        "p_fair": row.get("p_fair"),
        "fair_source": row.get("fair_source"),
        "sharp_book": row.get("sharp_book"),
        "line_gain": row.get("line_gain"),
        "filter_passed": row.get("filter_passed", False),
        "pipeline": "nba_shadow",
        "status": "paper",
        "reject_reason": row.get("reject_reason"),
    }
    if base["play_type"] == "prop":
        base["player_name"] = row.get("player_name")
        base["model_mean"] = row.get("model_mean")
        base["is_alternate"] = row.get("is_alternate")
    return base
