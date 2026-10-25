"""Persist per-game NFL totals board rows (measurement only — not the official card)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.utils.slate import parse_commence

logger = logging.getLogger(__name__)

DEFAULT_PATH = DATA_DIR / "nfl_game_totals.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_totals_board(path: Path | None = None) -> dict[str, Any]:
    path = path or DEFAULT_PATH
    if not path.exists():
        return {"games": [], "updated_at": None}
    return json.loads(path.read_text())


def save_totals_board(data: dict[str, Any], path: Path | None = None) -> None:
    path = path or DEFAULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    path.write_text(json.dumps(data, indent=2) + "\n")


def _kickoff_passed(kickoff: Any, *, now: datetime | None = None) -> bool:
    kick = parse_commence(kickoff)
    if kick is None:
        return False
    ref = now or datetime.now(timezone.utc)
    return kick <= ref


def upsert_totals_rows(
    rows: list[dict[str, Any]],
    *,
    path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Upsert by event_id; freeze pregame projection at kickoff (bug A)."""
    board = load_totals_board(path)
    existing = {str(g.get("event_id")): g for g in board.get("games") or []}
    for row in rows:
        eid = str(row.get("event_id") or "")
        if not eid:
            continue
        kick = row.get("kickoff") or row.get("commence_time")
        old = existing.get(eid)
        passed = _kickoff_passed(kick, now=now)
        if old and (old.get("frozen") or passed):
            merged = {**old}
            for key in ("home_score", "away_score", "result", "graded_at", "status"):
                if row.get(key) is not None:
                    merged[key] = row[key]
            if passed and not old.get("frozen"):
                for key in (
                    "projection_total",
                    "sim_median",
                    "sim_mean",
                    "market_line",
                    "sim_lean",
                    "p_over",
                    "p_under",
                    "p_push",
                    "blended_total",
                ):
                    if old.get(key) is not None:
                        merged[key] = old[key]
                merged["frozen"] = True
            existing[eid] = merged
            continue
        new_row = {
            **row,
            "event_id": eid,
            "kickoff": kick,
            "updated_at": _now(),
            "frozen": False,
        }
        existing[eid] = new_row
    board["games"] = list(existing.values())
    save_totals_board(board, path)
    return board
