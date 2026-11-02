"""Closing-line value for NFL player props (from recorded prop line history)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sharp_scout.data import line_store
from sharp_scout.ledger.clv import compute_clv_for_play
from sharp_scout.props.line_snapshots import closing_prop_sample

logger = logging.getLogger(__name__)


def finalize_prop_closing_lines(
    ledger: dict[str, Any],
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> int:
    from sharp_scout.props.actuals import is_prop_play

    hist = history if history is not None else line_store.load_history()
    clock = now or datetime.now(timezone.utc)
    updated = 0
    for play in ledger.get("plays") or []:
        if not is_prop_play(play):
            continue
        close = closing_prop_sample(play, history=hist)
        if not close:
            continue
        if not force and play.get("clv_at") and str(close.get("ts") or "") <= str(play.get("clv_at") or ""):
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
        logger.info("Prop CLV: refreshed closing lines for %d plays", updated)
    return updated
