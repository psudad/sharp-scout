"""Record NFL player-prop lines from existing Odds API event payloads (no extra credits)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from sharp_scout.config import get_settings
from sharp_scout.data import line_store
from sharp_scout.data.odds_api import is_demo_nfl_event

logger = logging.getLogger(__name__)


def _norm_player(name: str) -> str:
    return " ".join((name or "").lower().split())


def prop_series_key(event_id: Any, market: str, side: str, player: str, line: Any) -> str:
    return f"{event_id}|{market}|{side}|{_norm_player(player)}|{line}"


def record_prop_snapshots_from_events(
    events: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    path: Any = None,
) -> int:
    settings = get_settings()
    markets = set(settings.prop_market_list or [])
    history = line_store.load_history(path)
    ts = (now or datetime.now(timezone.utc)).isoformat()
    sharp_books = line_store._sharp_book_set()
    added = 0

    for ev in events:
        if is_demo_nfl_event(ev):
            continue
        eid = ev.get("event_id")
        if eid is None:
            continue
        for book_key, bm in (ev.get("bookmakers") or {}).items():
            is_sharp = bm.get("is_sharp") or book_key in sharp_books
            for market, outcomes in (bm.get("markets") or {}).items():
                if market not in markets:
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
                    samples.append(
                        {
                            "ts": ts,
                            "book": book_key,
                            "line": line,
                            "price": price,
                            "is_sharp": is_sharp,
                        }
                    )
                    added += 1

    if added:
        line_store.save_history(history, path)
        logger.info("props line_store: recorded %d prop samples", added)
    return added


def closing_prop_sample(
    play: dict[str, Any],
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
    path: Any = None,
) -> dict[str, Any] | None:
    """Last Pinnacle-preferred sample at/before kickoff for this prop bet."""
    eid = play.get("event_id")
    market = str(play.get("market") or "")
    side = str(play.get("side") or "")
    player = str(play.get("player_name") or "")
    line = play.get("line")
    if not eid or not market or not side or not player or line is None:
        return None
    hist = history if history is not None else line_store.load_history(path)
    key = prop_series_key(eid, market, side, player, line)
    samples = list(hist.get(key, []))
    if not samples:
        return None
    kick = line_store._parse_ts(play.get("kickoff") or play.get("commence_time"))
    if kick is not None:
        eligible = [s for s in samples if (line_store._parse_ts(s.get("ts")) or kick) <= kick]
        if eligible:
            samples = eligible

    def pref(s: dict[str, Any]) -> tuple[int, str]:
        book = str(s.get("book") or "").lower()
        return (0 if book == "pinnacle" else 1 if s.get("is_sharp") else 2, str(s.get("ts") or ""))

    return max(samples, key=pref)
