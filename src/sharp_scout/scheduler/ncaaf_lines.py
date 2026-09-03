"""Build per-game NCAAF line-snapshot run plan (opening + pre-kick windows)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR, get_settings
from sharp_scout.utils.slate import (
    college_week_bounds,
    filter_events_college_week,
    filter_events_in_college_week,
    following_college_week_bounds,
    parse_commence,
)

logger = logging.getLogger(__name__)

PLAN_PATH = DATA_DIR / "ncaaf_line_plan.json"
ET = ZoneInfo("America/New_York")

# Monday 10:00 ET — weekly opening-line capture when the college week starts.
OPENING_HOUR_ET = 10
OPENING_MINUTE = 0
# Sunday 18:00 ET — optional early capture when books post before Monday.
EARLY_OPENING_HOUR_ET = 18
EARLY_OPENING_MINUTE = 0

DEFAULT_LINE_WINDOWS_HOURS = (6.0, 4.0, 3.0, 1.0)

# Windows that trigger a full board rebuild (not just a line snapshot): the public
# report — plays, splits, open→now movement, When-to-bet — refreshes before kickoff.
REBUILD_WINDOWS_HOURS = (3.0, 1.0)


def _next_weekday_at(
    now: datetime,
    *,
    weekday: int,
    hour: int,
    minute: int,
) -> datetime:
    """Next (or current) occurrence of weekday at hour:minute ET, as UTC."""
    local = now.astimezone(ET)
    days_ahead = (weekday - local.weekday()) % 7
    target = (local + timedelta(days=days_ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if days_ahead == 0 and local > target:
        target += timedelta(days=7)
    return target.astimezone(timezone.utc)


def _next_monday_opening(now: datetime) -> datetime:
    """Next (or current) Monday 10:00 ET as UTC."""
    return _next_weekday_at(
        now, weekday=0, hour=OPENING_HOUR_ET, minute=OPENING_MINUTE
    )


def _next_sunday_early_opening(now: datetime) -> datetime:
    """Next (or current) Sunday 18:00 ET — early look at next week's board."""
    return _next_weekday_at(
        now, weekday=6, hour=EARLY_OPENING_HOUR_ET, minute=EARLY_OPENING_MINUTE
    )


def upcoming_ncaaf_events(*, now: datetime | None = None) -> list[dict[str, Any]]:
    """Odds API NCAAF board filtered to the current college week."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    if not settings.odds_api_key:
        return []
    try:
        from sharp_scout.data.odds_api import OddsClient

        events = OddsClient(sport="ncaaf").fetch_odds()
    except Exception as exc:  # noqa: BLE001
        logger.warning("NCAAF odds fetch for line plan failed: %s", exc)
        return []
    return filter_events_college_week(events, now=now, include_started=False)


def build_line_snapshot_plan(
    *,
    now: datetime | None = None,
    windows_hours: tuple[float, ...] | None = None,
    tolerance_minutes: int | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Plan opening + T-6h / T-4h / T-1h snapshots for each game in the college week."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    windows = windows_hours or DEFAULT_LINE_WINDOWS_HOURS
    tolerance = (
        tolerance_minutes
        if tolerance_minutes is not None
        else settings.pregame_window_tolerance_minutes
    )
    week_start, week_end = college_week_bounds(now)

    games = (
        filter_events_college_week(events, now=now, include_started=False)
        if events is not None
        else upcoming_ncaaf_events(now=now)
    )
    runs: list[dict[str, Any]] = []

    opening_at = _next_monday_opening(now)
    if opening_at >= now - timedelta(minutes=tolerance):
        runs.append(
            {
                "run_at": opening_at.isoformat(),
                "kind": "open",
                "window_hours": None,
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "matchup": "weekly_open",
                "kickoff": None,
                "event_id": None,
            }
        )

    early_open_at = _next_sunday_early_opening(now)
    if early_open_at >= now - timedelta(minutes=tolerance):
        next_start, next_end = following_college_week_bounds(now)
        runs.append(
            {
                "run_at": early_open_at.isoformat(),
                "kind": "open_early",
                "window_hours": None,
                "week_start": next_start.isoformat(),
                "week_end": next_end.isoformat(),
                "matchup": "weekly_open_early",
                "kickoff": None,
                "event_id": None,
            }
        )

    for ev in games:
        kickoff = parse_commence(ev.get("commence_time"))
        if kickoff is None:
            continue
        home = ev.get("home_team", "")
        away = ev.get("away_team", "")
        eid = str(ev.get("event_id"))
        matchup = f"{away}@{home}"
        for w in windows:
            run_at = kickoff - timedelta(hours=w)
            if run_at < now - timedelta(minutes=tolerance):
                continue
            runs.append(
                {
                    "run_at": run_at.isoformat(),
                    "kind": "prekick",
                    "window_hours": w,
                    "event_id": eid,
                    "matchup": matchup,
                    "kickoff": kickoff.isoformat(),
                    "week_start": week_start.isoformat(),
                }
            )

    runs.sort(key=lambda r: r["run_at"])

    run_hours: dict[str, list[int]] = {}
    for r in runs:
        dt = datetime.fromisoformat(r["run_at"])
        dow = dt.strftime("%A")
        run_hours.setdefault(dow, []).append(dt.hour)
    for dow in run_hours:
        run_hours[dow] = sorted(set(run_hours[dow]))

    return {
        "generated_at": now.isoformat(),
        "sport": "ncaaf",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "windows_hours": list(windows),
        "tolerance_minutes": tolerance,
        "opening_hour_et": OPENING_HOUR_ET,
        "early_opening_hour_et": EARLY_OPENING_HOUR_ET,
        "n_games": len(games),
        "n_runs": len(runs),
        "games": [
            {
                "event_id": ev.get("event_id"),
                "matchup": f"{ev.get('away_team')}@{ev.get('home_team')}",
                "kickoff": parse_commence(ev.get("commence_time")).isoformat()
                if parse_commence(ev.get("commence_time"))
                else None,
            }
            for ev in games
        ],
        "runs": runs,
        "run_hours_by_day": run_hours,
    }


def save_plan(plan: dict[str, Any], path: Path | None = None) -> Path:
    p = path or PLAN_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, indent=2) + "\n")
    return p


def load_plan(path: Path | None = None) -> dict[str, Any]:
    p = path or PLAN_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def should_run_now(
    plan: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    tolerance_minutes: int | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    plan = plan or load_plan()
    tolerance = tolerance_minutes if tolerance_minutes is not None else plan.get("tolerance_minutes", 25)
    tol = timedelta(minutes=tolerance)
    now = now or datetime.now(timezone.utc)
    matched: list[dict[str, Any]] = []
    for r in plan.get("runs") or []:
        try:
            run_at = datetime.fromisoformat(r["run_at"])
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if abs(now - run_at) <= tol:
            matched.append(r)
    return bool(matched), matched


def rebuild_due(
    plan: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    tolerance_minutes: int | None = None,
    rebuild_windows: tuple[float, ...] = REBUILD_WINDOWS_HOURS,
) -> tuple[bool, list[dict[str, Any]]]:
    """True when a pre-kick window that warrants a full board rebuild is due.

    Only pre-kick game windows (T-3h / T-1h by default) trigger a rebuild — weekly
    opening captures still run as plain snapshots.
    """
    ok, matched = should_run_now(plan, now=now, tolerance_minutes=tolerance_minutes)
    if not ok:
        return False, []
    windows = set(rebuild_windows)
    hits = [
        r
        for r in matched
        if r.get("kind") == "prekick" and float(r.get("window_hours") or 0) in windows
    ]
    return bool(hits), hits
