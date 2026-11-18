"""NCAAM morning preview artifacts (read-only helpers for site + tests)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR
from sharp_scout.ncaam.lock import find_play

ET = ZoneInfo("America/New_York")
PREVIEW_LATEST_PATH = DATA_DIR / "ncaam_preview_latest.json"
NCAAM_PREVIEW_DIR = DATA_DIR / "ncaam"


def preview_path_for_day(et_day: date) -> Path:
    return NCAAM_PREVIEW_DIR / f"preview_{et_day.strftime('%Y%m%d')}.json"


def preview_already_ran(et_day: date) -> bool:
    return preview_path_for_day(et_day).is_file()


def load_preview(*, et_day: date | None = None) -> dict[str, Any]:
    et_day = et_day or datetime.now(ET).date()
    for path in (preview_path_for_day(et_day), PREVIEW_LATEST_PATH):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            if data.get("et_day") == et_day.isoformat() or path == PREVIEW_LATEST_PATH:
                return data
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def ledger_overlay_status(ledger: dict[str, Any], espn_id: str) -> str | None:
    play = find_play(ledger, espn_id)
    if not play:
        return None
    if play.get("side") and str(play.get("status") or "").lower() not in ("no_play", "missed"):
        return "locked"
    st = str(play.get("status") or "").lower()
    if st in ("no_play", "missed"):
        return "passed_at_lock"
    return None