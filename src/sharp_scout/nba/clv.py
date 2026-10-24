"""NBA shadow CLV — game lines and player props."""

from __future__ import annotations

import logging
from typing import Any

from sharp_scout.data import line_store
from sharp_scout.ledger.clv import compute_clv_for_play, summarize_clv
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.line_store import prop_series_key

logger = logging.getLogger(__name__)


def _closing_from_samples(
    samples: list[dict[str, Any]],
    *,
    kickoff: Any,
    preferred_books: list[str] | None = None,
) -> dict[str, Any] | None:
    if not samples:
        return None
    from sharp_scout.config import get_settings

    pref = preferred_books or (get_settings().sharp_books + ["circa", "consensus"])
    ko = line_store._parse_ts(kickoff)
    eligible = samples
    if ko is not None:
        before = [s for s in samples if (line_store._parse_ts(s.get("ts")) or ko) <= ko]
        eligible = before or samples

    def sort_ts(s: dict[str, Any]) -> str:
        return str(s.get("ts") or "")

    for book in pref:
        book_samples = [s for s in eligible if s.get("book") == book]
        if book_samples:
            return max(book_samples, key=sort_ts)
    return max(eligible, key=sort_ts)


def finalize_nba_clv(
    ledger: dict[str, Any],
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
    history_path: Any = None,
) -> int:
    hist = history if history is not None else line_store.load_history(history_path or nba_paths.NBA_LINE_HISTORY_PATH)
    updated = 0
    for play in ledger.get("plays") or []:
        if play.get("clv_at") is not None:
            continue
        market = str(play.get("market") or "")
        side = str(play.get("side") or "")
        eid = play.get("event_id")
        if market.startswith("player_"):
            key = prop_series_key(eid, market, side, play.get("player_name") or "", play.get("line"))
            close = _closing_from_samples(hist.get(key, []), kickoff=play.get("kickoff"))
        else:
            close = line_store.closing_sample(
                eid,
                market,
                side,
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
        logger.info("NBA CLV: finalized %d plays", updated)
    return updated


def summarize_nba_clv(ledger: dict[str, Any]) -> dict[str, Any]:
    base = summarize_clv(ledger)
    by_type: dict[str, list[float]] = {}
    for p in ledger.get("plays") or []:
        if p.get("clv_prob") is None:
            continue
        kind = "prop" if p.get("play_type") == "prop" else str(p.get("market") or "side")
        by_type.setdefault(kind, []).append(float(p["clv_prob"]))
    base["by_market_avg_clv_prob"] = {
        k: round(sum(v) / len(v), 4) for k, v in sorted(by_type.items())
    }
    return base
