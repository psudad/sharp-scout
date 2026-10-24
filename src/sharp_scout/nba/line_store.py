"""NBA shadow line history — game lines + player props for CLV."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from sharp_scout.config import get_settings
from sharp_scout.data import line_store
from sharp_scout.nba import paths as nba_paths

logger = logging.getLogger(__name__)

GAME_MARKETS = ("spreads", "totals", "h2h")


def prop_series_key(event_id: Any, market: str, side: str, player: str, line: Any) -> str:
    return f"{event_id}|{market}|{side}|{_norm(player)}|{line}"


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


def record_nba_snapshot(
    events: Iterable[dict[str, Any]],
    *,
    sharp_only: bool = True,
    now: datetime | None = None,
    path: Any = None,
) -> dict[str, list[dict[str, Any]]]:
    """Append sharp book samples for sides + consensus books for props."""
    history = line_store.load_history(path or nba_paths.NBA_LINE_HISTORY_PATH)
    ts = (now or datetime.now(timezone.utc)).isoformat()
    settings = get_settings()
    sharp_books = set(settings.sharp_books) | {"circa"}
    added = 0

    for ev in events:
        eid = ev.get("event_id")
        if eid is None:
            continue
        for book_key, bm in (ev.get("bookmakers") or {}).items():
            is_sharp = bm.get("is_sharp") or book_key in sharp_books
            markets = bm.get("markets") or {}
            for market in GAME_MARKETS:
                if sharp_only and not is_sharp:
                    continue
                for o in markets.get(market) or []:
                    side = o.get("side")
                    price = o.get("price")
                    if side is None or price is None:
                        continue
                    key = line_store.series_key(eid, market, side)
                    samples = history.setdefault(key, [])
                    if line_store._dedupe_last(samples, book_key, o.get("point"), price):
                        continue
                    samples.append({"ts": ts, "book": book_key, "line": o.get("point"), "price": price})
                    added += 1

            for market, outcomes in markets.items():
                if not str(market).startswith("player_"):
                    continue
                if market not in settings.nba_prop_market_list:
                    continue
                for o in outcomes:
                    side = str(o.get("side") or o.get("name") or "").lower()
                    if side not in ("over", "under"):
                        continue
                    price = o.get("price")
                    line = o.get("point")
                    player = o.get("description") or o.get("player") or ""
                    if price is None or line is None or not player:
                        continue
                    key = prop_series_key(eid, market, side, player, line)
                    samples = history.setdefault(key, [])
                    if line_store._dedupe_last(samples, book_key, line, price):
                        continue
                    samples.append({"ts": ts, "book": book_key, "line": line, "price": price})
                    added += 1

    if added:
        line_store.save_history(history, path or nba_paths.NBA_LINE_HISTORY_PATH)
        logger.info("nba line_store: recorded %d samples", added)
    return history
