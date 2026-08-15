"""Build and check pregame run plans from the NFL weekly schedule."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from sharp_scout.config import DATA_DIR, get_settings

logger = logging.getLogger(__name__)

PLAN_PATH = DATA_DIR / "pregame_run_plan.json"
GAMES_CSV_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
)
ET = ZoneInfo("America/New_York")


def _parse_kickoff(gameday: str, gametime: str | None) -> datetime | None:
    if not gameday:
        return None
    time_str = (gametime or "").strip() or "13:00"
    try:
        local = datetime.strptime(f"{gameday} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return local.replace(tzinfo=ET).astimezone(timezone.utc)


def load_games_csv(url: str = GAMES_CSV_URL) -> list[dict[str, Any]]:
    """Fetch nflverse schedule (Lee Sharpe nfldata / games.csv)."""
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                logger.warning("Schedule download failed: %s", resp.status_code)
                return []
            text = resp.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("Schedule download error: %s", exc)
        return []

    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(StringIO(text)):
        rows.append(row)
    return rows


def upcoming_games_from_schedule(
    *,
    now: datetime | None = None,
    horizon_days: int = 10,
    seasons: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Return upcoming games with UTC kickoff from nflverse games.csv."""
    settings = get_settings()
    seasons = seasons or settings.seasons
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(days=horizon_days)
    season_set = {str(s) for s in seasons}

    games: list[dict[str, Any]] = []
    for row in load_games_csv():
        if row.get("season") not in season_set:
            continue
        kickoff = _parse_kickoff(row.get("gameday", ""), row.get("gametime"))
        if kickoff is None or kickoff <= now or kickoff > horizon:
            continue
        # Skip completed games when scores are present
        if row.get("home_score") and row.get("away_score"):
            try:
                if float(row["home_score"]) >= 0 and float(row["away_score"]) >= 0:
                    continue
            except ValueError:
                pass
        games.append(
            {
                "game_id": row.get("game_id"),
                "season": int(row["season"]),
                "week": row.get("week"),
                "game_type": row.get("game_type"),
                "kickoff": kickoff,
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "matchup": f"{row.get('away_team')}@{row.get('home_team')}",
            }
        )
    games.sort(key=lambda g: g["kickoff"])
    return games


def merge_odds_kickoffs(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Overlay Odds API commence times when key is set (more accurate for listed slates)."""
    settings = get_settings()
    if not settings.odds_api_key:
        return games
    try:
        from sharp_scout.data.odds_api import OddsClient

        events = OddsClient().fetch_events()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Odds API schedule merge skipped: %s", exc)
        return games

    by_matchup: dict[str, datetime] = {}
    for ev in events:
        home = ev.get("home_team")
        away = ev.get("away_team")
        ct = ev.get("commence_time")
        if home and away and ct:
            by_matchup[f"{away}@{home}"] = ct

    for g in games:
        key = g.get("matchup")
        if key in by_matchup:
            g["kickoff"] = by_matchup[key]
            g["kickoff_source"] = "odds_api"
        else:
            g["kickoff_source"] = "nflverse"
    return games


def build_run_plan(
    *,
    now: datetime | None = None,
    horizon_days: int = 10,
    windows_hours: list[float] | None = None,
    tolerance_minutes: int | None = None,
) -> dict[str, Any]:
    """Compute UTC run times at T-12h / T-3h / T-1h (± tolerance) for each upcoming game."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    windows = windows_hours or settings.pregame_windows
    tolerance = (
        tolerance_minutes if tolerance_minutes is not None else settings.pregame_window_tolerance_minutes
    )

    games = merge_odds_kickoffs(upcoming_games_from_schedule(now=now, horizon_days=horizon_days))
    runs: list[dict[str, Any]] = []
    for g in games:
        kickoff = g["kickoff"]
        for w in windows:
            run_at = kickoff - timedelta(hours=w)
            if run_at < now - timedelta(minutes=tolerance):
                continue
            runs.append(
                {
                    "run_at": run_at.isoformat(),
                    "window_hours": w,
                    "game_id": g.get("game_id"),
                    "matchup": g.get("matchup"),
                    "kickoff": kickoff.isoformat(),
                    "season": g.get("season"),
                    "week": g.get("week"),
                    "game_type": g.get("game_type"),
                }
            )
    runs.sort(key=lambda r: r["run_at"])

    # Unique UTC hours for documentation / debugging
    run_hours: dict[str, list[int]] = {}
    for r in runs:
        dt = datetime.fromisoformat(r["run_at"])
        dow = dt.strftime("%A")
        run_hours.setdefault(dow, []).append(dt.hour)
    for dow in run_hours:
        run_hours[dow] = sorted(set(run_hours[dow]))

    return {
        "generated_at": now.isoformat(),
        "horizon_days": horizon_days,
        "windows_hours": windows,
        "tolerance_minutes": tolerance,
        "n_games": len(games),
        "n_runs": len(runs),
        "games": [
            {
                "game_id": g.get("game_id"),
                "matchup": g.get("matchup"),
                "kickoff": g["kickoff"].isoformat(),
                "kickoff_source": g.get("kickoff_source", "nflverse"),
            }
            for g in games
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


def plan_is_stale(plan: dict[str, Any], max_age_hours: float = 36) -> bool:
    if not plan.get("generated_at"):
        return True
    try:
        generated = datetime.fromisoformat(plan["generated_at"])
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - generated > timedelta(hours=max_age_hours)


def should_run_now(
    plan: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    tolerance_minutes: int | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    """True when `now` is within tolerance of any planned pregame run time."""
    settings = get_settings()
    plan = plan or load_plan()
    tolerance = (
        tolerance_minutes if tolerance_minutes is not None else plan.get("tolerance_minutes")
    )
    if tolerance is None:
        tolerance = settings.pregame_window_tolerance_minutes
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
