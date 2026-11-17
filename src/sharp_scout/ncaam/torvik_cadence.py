"""Torvik cache refresh cadence (box scheduler + health staleness)."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

TORVIK_UA = "SharpScout/1.0 jayegg-tr17 (github.com/psudad/sharp-scout; NCAAM ratings cache)"

CadenceMode = Literal["daily", "weekly"]
CadenceSetting = Literal["daily", "weekly", "auto"]

STALE_MAX_AGE_DAYS: dict[CadenceMode, float] = {"daily": 2.0, "weekly": 8.0}


def torvik_cadence_setting() -> CadenceSetting:
    raw = (os.environ.get("TORVIK_CADENCE") or "auto").strip().lower()
    if raw in ("daily", "weekly", "auto"):
        return raw  # type: ignore[return-value]
    return "auto"


def effective_cadence(day: date | None = None) -> CadenceMode:
    """Daily Nov–Dec ET; weekly Jan–Oct (incl. postseason / off-season)."""
    setting = torvik_cadence_setting()
    if setting in ("daily", "weekly"):
        return setting
    day = day or datetime.now(ET).date()
    if day.month in (11, 12):
        return "daily"
    return "weekly"


def stale_threshold_days(day: date | None = None) -> float:
    return STALE_MAX_AGE_DAYS[effective_cadence(day)]


def refresh_due_today(day: date | None = None) -> bool:
    """Whether the box refresh script should run a fetch today (ET)."""
    day = day or datetime.now(ET).date()
    cadence = effective_cadence(day)
    if cadence == "daily":
        return True
    return day.weekday() == 0  # Monday


def freshness_window(day: date | None = None) -> timedelta:
    """How long committed cache remains 'fresh enough' to skip a box refresh."""
    day = day or datetime.now(ET).date()
    if effective_cadence(day) == "daily":
        return timedelta(days=1)
    return timedelta(days=7)


def parse_retrieved_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)