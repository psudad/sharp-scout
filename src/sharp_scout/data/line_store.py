"""Timestamped line-history store — shared by CLV (closing lines) and steam detection.

`line_memory.py` keeps a single first-seen "open" line per game/market for RLM. This
module instead keeps an **append-only, timestamped** series of sharp-book lines per
event/market/side so we can measure:

* the **closing line** (last sample at/before kickoff) → Closing Line Value, and
* **steam** (magnitude × speed × number of sharp books moving) in a pre-kick window.

Samples are written to ``data/line_history.json`` as::

    {
      "<event_id>|<market>|<side>": [
        {"ts": ISO8601, "book": "pinnacle", "line": -2.5, "price": -110},
        ...
      ]
    }

The store is intentionally file-based (no DB) to match the rest of the repo and to keep
GitHub Actions runs cheap and stateless-friendly (committed alongside the ledger).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sharp_scout.config import DATA_DIR, get_settings

logger = logging.getLogger(__name__)

LINE_HISTORY_PATH = DATA_DIR / "line_history.json"

# Markets we track lines for (spreads/totals carry a point; h2h is price-only).
TRACKED_MARKETS = ("spreads", "totals", "h2h")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def series_key(event_id: Any, market: str, side: str) -> str:
    return f"{event_id}|{market}|{side}"


def load_history(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    p = path or LINE_HISTORY_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_history(history: dict[str, list[dict[str, Any]]], path: Path | None = None) -> Path:
    p = path or LINE_HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(history, indent=2, default=str) + "\n")
    return p


def _sharp_book_set() -> set[str]:
    return set(get_settings().sharp_books) | {"circa"}


def _dedupe_last(samples: list[dict[str, Any]], book: str, line: Any, price: Any) -> bool:
    """True if the most recent sample for this book already has the same line+price."""
    for s in reversed(samples):
        if s.get("book") == book:
            return s.get("line") == line and s.get("price") == price
    return False


def record_snapshot(
    events: Iterable[dict[str, Any]],
    *,
    sharp_only: bool = True,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Append current sharp-book lines from Odds API events to the history store.

    Only records a new sample when the line or price changed for that book (so polling
    every few minutes stays compact). ``sharp_only`` restricts to Pinnacle/Circa/etc.
    """
    history = load_history(path)
    ts = (now or datetime.now(timezone.utc)).isoformat()
    sharp_books = _sharp_book_set()
    added = 0

    for ev in events:
        eid = ev.get("event_id")
        if eid is None:
            continue
        books = ev.get("bookmakers") or {}
        for book_key, bm in books.items():
            if sharp_only and not (bm.get("is_sharp") or book_key in sharp_books):
                continue
            markets = bm.get("markets") or {}
            for market in TRACKED_MARKETS:
                for o in markets.get(market) or []:
                    side = o.get("side")
                    price = o.get("price")
                    line = o.get("point")
                    if side is None or price is None:
                        continue
                    key = series_key(eid, market, side)
                    samples = history.setdefault(key, [])
                    if _dedupe_last(samples, book_key, line, price):
                        continue
                    samples.append(
                        {"ts": ts, "book": book_key, "line": line, "price": price}
                    )
                    added += 1

    if added:
        save_history(history, path)
        logger.info("line_store: recorded %d new line samples", added)
    return history


def samples_for(
    event_id: Any,
    market: str,
    side: str,
    *,
    path: Path | None = None,
    history: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    hist = history if history is not None else load_history(path)
    return list(hist.get(series_key(event_id, market, side), []))


def opening_sample(
    event_id: Any,
    market: str,
    side: str,
    *,
    preferred_books: list[str] | None = None,
    path: Path | None = None,
    history: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Earliest sample we ever recorded — the opening line we first saw.

    Prefers a sharp benchmark book so "open → now" compares like with like; falls back
    to the oldest sample from any book.
    """
    samples = samples_for(event_id, market, side, path=path, history=history)
    if not samples:
        return None

    def sort_ts(s: dict[str, Any]) -> str:
        return str(s.get("ts") or "")

    pref = preferred_books or (get_settings().sharp_books + ["circa"])
    for book in pref:
        book_samples = [s for s in samples if s.get("book") == book]
        if book_samples:
            return min(book_samples, key=sort_ts)
    return min(samples, key=sort_ts)


def closing_sample(
    event_id: Any,
    market: str,
    side: str,
    *,
    kickoff: Any = None,
    preferred_books: list[str] | None = None,
    path: Path | None = None,
    history: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Latest sample at/before kickoff — the closing line for CLV.

    Prefers a sharp benchmark book (Pinnacle → Circa → …) when multiple books have a
    final sample; falls back to the single most recent sample otherwise.
    """
    samples = samples_for(event_id, market, side, path=path, history=history)
    if not samples:
        return None

    ko = _parse_ts(kickoff)
    eligible = samples
    if ko is not None:
        before = [s for s in samples if (_parse_ts(s.get("ts")) or ko) <= ko]
        eligible = before or samples  # if nothing before kickoff, use what we have

    pref = preferred_books or (get_settings().sharp_books + ["circa"])

    def sort_ts(s: dict[str, Any]) -> str:
        return str(s.get("ts") or "")

    for book in pref:
        book_samples = [s for s in eligible if s.get("book") == book]
        if book_samples:
            return max(book_samples, key=sort_ts)
    return max(eligible, key=sort_ts)
