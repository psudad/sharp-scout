"""NCAAM Odds API daily credit budget (120/day) and remaining-header floor."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR

NCAAM_DAILY_CAP = 120
REMAINING_HEADER_FLOOR = 80
CREDITS_PER_ODDS_CALL = 2
NCAAM_DATA = DATA_DIR / "ncaam"
ET = ZoneInfo("America/New_York")


def _today_et() -> date:
    return datetime.now(ET).date()


def _budget_path(day: date | None = None) -> Path:
    day = day or _today_et()
    return NCAAM_DATA / f"odds_budget_{day.strftime('%Y%m%d')}.json"


def load_budget(day: date | None = None) -> dict[str, Any]:
    p = _budget_path(day)
    if not p.exists():
        return {"date": (day or _today_et()).isoformat(), "used": 0}
    return json.loads(p.read_text())


def save_budget(data: dict[str, Any], day: date | None = None) -> None:
    p = _budget_path(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")


def credits_used_today(day: date | None = None) -> int:
    return int(load_budget(day).get("used") or 0)


def can_spend(*, cost: int = CREDITS_PER_ODDS_CALL, day: date | None = None) -> bool:
    return credits_used_today(day) + cost <= NCAAM_DAILY_CAP


def record_spend(cost: int, *, day: date | None = None, remaining_header: int | None = None) -> None:
    data = load_budget(day)
    data["used"] = int(data.get("used") or 0) + int(cost)
    if remaining_header is not None:
        data["last_remaining_header"] = remaining_header
    save_budget(data, day)


def last_remaining_header(day: date | None = None) -> int | None:
    v = load_budget(day).get("last_remaining_header")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def should_skip_snapshot(*, remaining_header: int | None, day: date | None = None) -> tuple[bool, str]:
    if remaining_header is None:
        remaining_header = last_remaining_header(day)
    if not can_spend(day=day):
        return True, "ncaam_daily_cap"
    if remaining_header is not None and remaining_header < REMAINING_HEADER_FLOOR:
        return True, "global_remaining_floor"
    return False, ""
