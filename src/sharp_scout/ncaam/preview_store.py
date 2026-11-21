"""NCAAM morning preview artifacts (read-only helpers for site + tests)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR
from sharp_scout.ncaam.lock import LockWindow, find_play, lock_window

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


PREVIEW_STATE_ACTIVE = "active"
PREVIEW_STATE_DROPPED = "no_longer_qualifies"


def _tip_et_date(pick: dict[str, Any]) -> date | None:
    iso = pick.get("tip") or pick.get("kickoff") or pick.get("commence_time")
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(ET).date()
    except ValueError:
        return None


def is_open_preview_pick(
    pick: dict[str, Any],
    ledger: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """True when a stored preview row should appear in the public Preview section."""
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)
    today = now.date()
    if _tip_et_date(pick) != today:
        return False
    if str(pick.get("preview_state") or PREVIEW_STATE_ACTIVE).lower() != PREVIEW_STATE_ACTIVE:
        return False
    eid = str(pick.get("espn_id") or pick.get("event_id") or "")
    if eid and ledger_overlay_status(ledger, eid):
        return False
    tip_raw = pick.get("tip")
    if not tip_raw:
        return False
    try:
        tip = datetime.fromisoformat(str(tip_raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if lock_window(now.astimezone(timezone.utc), tip) != LockWindow.TOO_EARLY:
        return False
    return True


def open_preview_picks(
    picks: list[dict[str, Any]],
    ledger: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return [p for p in picks if is_open_preview_pick(p, ledger, now=now)]