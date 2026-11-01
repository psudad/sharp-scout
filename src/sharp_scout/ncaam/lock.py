"""Pick lock windows (T-90..T-25 primary, late T-25..T-5) and immutable ledger rows."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.ledger.tracker import load_ledger, save_ledger
from sharp_scout.ncaam.rules import MODEL_VERSION

LEDGER_PATH = DATA_DIR / "ncaam_ledger.json"

LOCKED_FIELDS = frozenset(
    {
        "id",
        "event_id",
        "espn_id",
        "market",
        "side",
        "line",
        "price",
        "book",
        "units",
        "locked_at",
        "tip",
        "lead_min",
        "inputs_sha256",
        "model_version",
        "home_team",
        "away_team",
        "p_true",
        "ev",
        "late_lock",
        "status",
    }
)


class LockWindow(str, Enum):
    PRIMARY = "primary"
    LATE = "late"
    MISSED = "missed"
    TOO_EARLY = "too_early"
    POST_TIP = "post_tip"


def lock_window(now: datetime, tip: datetime) -> LockWindow:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if tip.tzinfo is None:
        tip = tip.replace(tzinfo=timezone.utc)
    if now >= tip:
        return LockWindow.POST_TIP
    lead = (tip - now).total_seconds() / 60.0
    if lead > 90:
        return LockWindow.TOO_EARLY
    if lead > 25:
        return LockWindow.PRIMARY
    if lead > 5:
        return LockWindow.LATE
    return LockWindow.MISSED


def inputs_sha256(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _play_key(play: dict[str, Any]) -> str:
    return "|".join(
        [
            str(play.get("espn_id") or play.get("event_id") or ""),
            str(play.get("market") or ""),
        ]
    )


def find_play(ledger: dict[str, Any], espn_id: str) -> dict[str, Any] | None:
    for p in ledger.get("plays") or []:
        if str(p.get("espn_id") or p.get("event_id") or "") == str(espn_id):
            if p.get("market") in (None, "spreads", "h2h") and p.get("locked_at"):
                return p
    return None


def append_lock(
    play: dict[str, Any],
    *,
    path: Path | None = None,
    allow_no_play: bool = False,
) -> dict[str, Any]:
    """Append a locked pick or explicit no-play marker for the game."""
    ledger = load_ledger(path or LEDGER_PATH)
    plays: list[dict[str, Any]] = list(ledger.get("plays") or [])
    key = _play_key(play)
    for existing in plays:
        if _play_key(existing) == key and existing.get("locked_at"):
            return ledger
    now = datetime.now(timezone.utc)
    tip = play.get("tip")
    if isinstance(tip, str):
        tip = datetime.fromisoformat(tip.replace("Z", "+00:00"))
    if tip and now >= tip:
        raise ValueError("Refusing lock at or after tip")
    row = {
        "id": play.get("id") or str(uuid.uuid4()),
        "created_at": now.isoformat(),
        "locked_at": now.isoformat(),
        "model_version": MODEL_VERSION,
        **play,
    }
    if allow_no_play and not play.get("side"):
        row["status"] = "no_play"
    plays.append(row)
    ledger["plays"] = plays
    save_ledger(ledger, path or LEDGER_PATH)
    return ledger


def record_missed(espn_id: str, *, tip: datetime, path: Path | None = None) -> None:
    ledger = load_ledger(path or LEDGER_PATH)
    if find_play(ledger, espn_id):
        return
    append_lock(
        {
            "espn_id": espn_id,
            "event_id": espn_id,
            "status": "missed",
            "tip": tip.isoformat(),
            "lead_min": None,
            "market": "spreads",
            "side": None,
            "inputs_sha256": "",
        },
        path=path,
        allow_no_play=True,
    )
