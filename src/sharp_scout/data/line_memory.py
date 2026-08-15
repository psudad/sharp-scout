"""Remember first-seen lines as opening lines for RLM when Action Network omits them."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR

logger = logging.getLogger(__name__)

OPEN_LINES_PATH = DATA_DIR / "open_lines.json"


def _load() -> dict[str, float]:
    if not OPEN_LINES_PATH.exists():
        return {}
    try:
        data = json.loads(OPEN_LINES_PATH.read_text())
        return {str(k): float(v) for k, v in data.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save(memory: dict[str, float]) -> None:
    OPEN_LINES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPEN_LINES_PATH.write_text(json.dumps(memory, indent=2) + "\n")


def overlay_open_lines(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set open_line from first-seen current_line per game/market (for RLM)."""
    memory = _load()
    updated = False
    for g in games:
        gid = str(g.get("game_id") or "")
        if not gid:
            continue
        markets = g.get("markets") or {}
        for mkey in ("spread", "total"):
            block = markets.get(mkey) or {}
            cur = block.get("current_line")
            if cur is None:
                continue
            try:
                cur_f = float(cur)
            except (TypeError, ValueError):
                continue
            mem_key = f"{gid}|{mkey}"
            if mem_key not in memory:
                memory[mem_key] = cur_f
                updated = True
            block["open_line"] = memory[mem_key]
    if updated:
        _save(memory)
        logger.info("Stored opening lines for %d keys in %s", len(memory), OPEN_LINES_PATH)
    return games
