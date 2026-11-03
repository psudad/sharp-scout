"""Manual NBA paper-ledger overrides (voids) that survive re-scans and settlement.

``data/shadow/nba_ledger_overrides.json`` lists plays to void. Every scan, settle and page
build re-applies it, so a run that started from an older checkout cannot bring a voided
play back, and a later scan cannot log the same bet again.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.nba import paths as nba_paths

OVERRIDES_FILENAME = "nba_ledger_overrides.json"


def overrides_path() -> Path:
    return nba_paths.SHADOW_DIR / OVERRIDES_FILENAME


def load_nba_overrides(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or overrides_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    rows = data.get("voids") if isinstance(data, dict) else None
    return [r for r in rows or [] if isinstance(r, dict)]


def _bet_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("event_id") or ""),
        str(row.get("market") or "").lower(),
        str(row.get("side") or "").lower(),
    )


def _matches(row: dict[str, Any], ov: dict[str, Any]) -> bool:
    if ov.get("id") and row.get("id") == ov.get("id"):
        return True
    if ov.get("ledger_id") and row.get("ledger_id") == ov.get("ledger_id"):
        return True
    if ov.get("event_id") and ov.get("market") and ov.get("side"):
        return _bet_key(row) == _bet_key(ov)
    return False


def voided_override_for(row: dict[str, Any], overrides: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    for ov in overrides if overrides is not None else load_nba_overrides():
        if _matches(row, ov):
            return ov
    return None


def apply_nba_ledger_overrides(
    ledger: dict[str, Any],
    overrides: list[dict[str, Any]] | None = None,
) -> int:
    """Force matching ledger rows to VOID at 0u. Returns how many rows changed."""
    overrides = overrides if overrides is not None else load_nba_overrides()
    if not overrides:
        return 0
    changed = 0
    for play in ledger.get("plays") or []:
        ov = voided_override_for(play, overrides)
        if ov is None:
            continue
        reason = str(ov.get("reason") or "manual void")
        if (
            str(play.get("status") or "").lower() == "void"
            and play.get("void_reason") == reason
            and float(play.get("pnl_units") or 0.0) == 0.0
            and float(play.get("units") or 0.0) == 0.0
        ):
            continue
        prev_status = play.get("status")
        if str(prev_status or "").lower() != "void" or "pre_void_status" not in play:
            play["pre_void_status"] = prev_status
            play["pre_void_pnl_units"] = play.get("pnl_units")
            play["pre_void_units"] = play.get("units")
        play["status"] = "void"
        play["units"] = 0.0
        play["pnl_units"] = 0.0
        play["void_reason"] = reason
        play["exclude_reason"] = reason
        play["voided_at"] = str(ov.get("voided_at") or datetime.now(timezone.utc).isoformat())
        try:
            from sharp_scout.nba.clv import sanitize_play_clv

            sanitize_play_clv(play, reason=reason)
        except Exception:  # noqa: BLE001
            pass
        if not play.get("settled_at"):
            play["settled_at"] = play["voided_at"]
        changed += 1
    return changed


def drop_voided_signals(
    signals: list[dict[str, Any]],
    overrides: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Remove scan signals that match a voided bet (same game, market and side)."""
    overrides = overrides if overrides is not None else load_nba_overrides()
    if not overrides:
        return list(signals)
    return [s for s in signals if voided_override_for(s, overrides) is None]
