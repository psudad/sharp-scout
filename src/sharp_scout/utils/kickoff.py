"""Kickoff parsing and pre-game eligibility (shared by ledgers)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def parse_kickoff_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def kickoff_still_future(row: dict[str, Any] | Any, *, now: datetime | None = None) -> bool:
    """True when kickoff is strictly after *now* (game has not started)."""
    now = now or datetime.now(timezone.utc)
    if isinstance(row, dict):
        raw = row.get("kickoff") or row.get("commence_time")
    else:
        raw = row
    kick = parse_kickoff_utc(raw)
    if kick is None:
        return False
    return kick > now


def kickoff_in_horizon(
    value: Any,
    hours: float,
    *,
    now: datetime | None = None,
) -> bool:
    """True when kickoff is strictly after *now* and within *hours* (same window as props)."""
    now = now or datetime.now(timezone.utc)
    kick = parse_kickoff_utc(value)
    if kick is None:
        return False
    horizon = now + timedelta(hours=hours)
    return kick > now and kick <= horizon


def logged_at_or_after_kickoff(
    row: dict[str, Any],
    *,
    logged_at_field: str = "first_seen_at",
) -> bool:
    """True when the row's first log timestamp is at or after scheduled kickoff."""
    kick = parse_kickoff_utc(row.get("kickoff"))
    if kick is None:
        return False
    logged = parse_kickoff_utc(row.get(logged_at_field) or row.get("created_at") or row.get("snapshot_at"))
    if logged is None:
        return False
    return logged >= kick
