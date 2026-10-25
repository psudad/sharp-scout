"""NBA shadow CLV — game lines and player props."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sharp_scout.data import line_store
from sharp_scout.ledger.clv import CLV_FIELDS, compute_clv_for_play, summarize_clv
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.line_store import prop_series_key
from sharp_scout.utils.kickoff import parse_kickoff_utc
from sharp_scout.utils.odds import american_to_implied_prob

logger = logging.getLogger(__name__)

# Reject extreme exchange placeholders (e.g. Betfair -5000 on a Christmas future).
MAX_ABS_H2H_CLOSE = 1200
MAX_CLOSE_JUMP_VS_BET = 350  # American odds points vs our bet price on h2h


def sanitize_play_clv(play: dict[str, Any], *, reason: str | None = None) -> None:
    for field in CLV_FIELDS:
        play.pop(field, None)
    if reason:
        play["clv_excluded_reason"] = reason


def close_sample_trustworthy(play: dict[str, Any], close: dict[str, Any]) -> tuple[bool, str | None]:
    """Return (ok, exclude_reason)."""
    market = str(play.get("market") or "")
    bet_price = play.get("price")
    close_price = close.get("price")
    kick = parse_kickoff_utc(play.get("kickoff"))
    close_ts = line_store._parse_ts(close.get("ts"))

    if kick is not None and close_ts is not None:
        # Closing line captured weeks before tip — not a real close.
        if kick - close_ts > timedelta(hours=48):
            return False, "close_too_early_vs_kickoff"

    if close_price is None:
        return False, "missing_close_price"

    try:
        cp = float(close_price)
        bp = float(bet_price) if bet_price is not None else None
    except (TypeError, ValueError):
        return False, "invalid_close_price"

    if market == "h2h":
        if abs(cp) > MAX_ABS_H2H_CLOSE:
            return False, "implausible_h2h_close"
        if bp is not None and abs(cp - bp) > MAX_CLOSE_JUMP_VS_BET and abs(cp) > abs(bp):
            return False, "implausible_h2h_jump"

    close_book = str(close.get("book") or "").lower()
    if not close_book or close_book in ("unknown", "none"):
        return False, "missing_close_book"

    return True, None


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
    force: bool = False,
) -> int:
    hist = history if history is not None else line_store.load_history(history_path or nba_paths.NBA_LINE_HISTORY_PATH)
    updated = 0
    for play in ledger.get("plays") or []:
        if play.get("clv_at") is not None and not force:
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
        ok, reason = close_sample_trustworthy(play, close)
        if not ok:
            sanitize_play_clv(play, reason=reason)
            updated += 1
            continue
        compute_clv_for_play(
            play,
            close.get("line"),
            close.get("price"),
            close_book=close.get("book"),
            at=close.get("ts"),
        )
        play.pop("clv_excluded_reason", None)
        updated += 1
    if updated:
        logger.info("NBA CLV: finalized %d plays", updated)
    return updated


def recompute_nba_clv_summary_fields(ledger: dict[str, Any]) -> int:
    """Re-apply CLV sanity to every play that still has close fields."""
    changed = 0
    for play in ledger.get("plays") or []:
        if play.get("clv_at") is None:
            continue
        close = {
            "line": play.get("close_line"),
            "price": play.get("close_price"),
            "book": play.get("close_book"),
            "ts": play.get("clv_at"),
        }
        ok, reason = close_sample_trustworthy(play, close)
        if not ok:
            sanitize_play_clv(play, reason=reason)
            changed += 1
    return changed


def summarize_nba_clv(ledger: dict[str, Any]) -> dict[str, Any]:
    plays = []
    for p in ledger.get("plays") or []:
        if p.get("clv_excluded_reason"):
            continue
        if p.get("clv_at"):
            plays.append(p)
    base = summarize_clv({"plays": plays})
    by_type: dict[str, list[float]] = {}
    for p in plays:
        if p.get("clv_prob") is None:
            continue
        kind = "prop" if p.get("play_type") == "prop" else str(p.get("market") or "side")
        by_type.setdefault(kind, []).append(float(p["clv_prob"]))
    base["by_market_avg_clv_prob"] = {
        k: round(sum(v) / len(v), 4) for k, v in sorted(by_type.items())
    }
    base["n_clv_excluded"] = sum(
        1 for p in ledger.get("plays") or [] if p.get("clv_excluded_reason")
    )
    return base


def h2h_close_implied_sanity(price: Any) -> bool:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return False
    if abs(p) > MAX_ABS_H2H_CLOSE:
        return False
    american_to_implied_prob(p)
    return True
