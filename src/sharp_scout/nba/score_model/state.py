"""Persist / restore live V2 score engine from ESPN-backed game history."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.data.espn_nba import fetch_espn_nba_finals_by_event, fetch_game_possessions
from sharp_scout.nba.franchises import is_nba_franchise, is_nba_regular_matchup
from sharp_scout.nba.score_model.engine import HistRow, V2Engine, V2Params, TeamPrior
from sharp_scout.nba.score_model.teams_geo import ALTITUDE_TEAMS, travel_miles
from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc

logger = logging.getLogger(__name__)

STATE_PATH = DATA_DIR / "paper" / "nba_score_model_state.json"
PRIORS_PATH = DATA_DIR / "paper" / "nba_score_model_priors.json"


def _season_label(dt: datetime) -> str:
    y = dt.year
    if dt.month >= 10:
        return f"{y}-{(y + 1) % 100:02d}"
    return f"{y - 1}-{y % 100:02d}"


def _season_start_date(when: datetime | None = None) -> date:
    when = when or datetime.now(timezone.utc)
    y = when.year if when.month >= 10 else when.year - 1
    return date(y, 10, 1)


def _game_key(g: dict[str, Any]) -> str:
    eid = g.get("event_id")
    if eid:
        return f"eid:{eid}"
    d = g.get("date")
    ds = d.date().isoformat() if isinstance(d, datetime) else str(d)
    return f"{g['away']}@{g['home']}@{ds}"


def _estimate_poss(hs: float, as_: float) -> float:
    return max((hs + as_) / 2.2, 90.0)


def _rest_days(team: str, dt: datetime, last: dict[str, datetime]) -> int | None:
    prev = last.get(team)
    if prev is None:
        return None
    day_k = kickoff_date_et(dt)
    day_p = kickoff_date_et(prev)
    if day_k is None or day_p is None:
        return max((dt.date() - prev.date()).days, 0)
    return max((day_k - day_p).days, 0)


def _three_in_four(team: str, day_et: date | None, team_dates_et: dict[str, list[date]]) -> bool:
    if day_et is None:
        return False
    window_start = day_et - timedelta(days=4)
    count = sum(1 for d in team_dates_et.get(team, []) if window_start < d < day_et)
    return count >= 2


def _games_from_scores(
    scores: list[dict[str, Any]],
    *,
    poss_cache: dict[str, float],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in scores:
        kick = parse_kickoff_utc(row.get("kickoff")) or datetime.now(timezone.utc)
        hs, as_ = float(row["home_score"]), float(row["away_score"])
        home = normalize_nba_team(str(row["home_team"]))
        away = normalize_nba_team(str(row["away_team"]))
        if not is_nba_regular_matchup(home, away):
            continue
        eid = str(row.get("event_id") or "")
        poss = poss_cache.get(eid) if eid else None
        if poss is None:
            if eid:
                try:
                    fetched = fetch_game_possessions(eid)
                    if fetched:
                        poss_cache[eid] = fetched
                        poss = fetched
                except Exception as exc:  # noqa: BLE001
                    logger.debug("poss fetch skipped %s: %s", eid, exc)
            if poss is None:
                poss = _estimate_poss(hs, as_)
        out.append(
            {
                "home": home,
                "away": away,
                "home_pts": hs,
                "away_pts": as_,
                "date": kick,
                "season": _season_label(kick),
                "game_poss": poss,
                "event_id": eid or None,
            }
        )
    out.sort(key=lambda g: g["date"])
    return out


def load_committed_priors(path: Path | None = None) -> dict[str, Any] | None:
    p = path or PRIORS_PATH
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def apply_committed_priors(engine: V2Engine, raw: dict[str, Any]) -> None:
    """Stage-2 style season entry from offline regressed end-of-prior-season ratings."""
    teams = raw.get("teams") or {}
    priors: dict[str, TeamPrior] = {}
    for team, p in teams.items():
        code = normalize_nba_team(str(team))
        if not is_nba_franchise(code):
            continue
        priors[code] = TeamPrior(
            off=float(p["off"]),
            def_=float(p["def_"] if "def_" in p else p.get("def", 112)),
            pace=float(p["pace"]),
        )
    engine.season_priors = priors
    engine.end_season_priors = dict(priors)
    engine.start_new_season()
    logger.info(
        "score engine: loaded priors for %s (%d teams)",
        raw.get("for_season"),
        len(priors),
    )


def engine_to_state(
    engine: V2Engine,
    *,
    processed: set[str],
    poss_cache: dict[str, float],
    last_processed_date: str | None,
) -> dict[str, Any]:
    return {
        "version": 2,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stage": engine.stage,
        "processed_keys": sorted(processed),
        "last_processed_date": last_processed_date,
        "poss_cache": poss_cache,
        "team_off": engine.team_off,
        "team_def": engine.team_def,
        "team_pace": engine.team_pace,
        "team_games": engine.team_games,
        "season_priors": {k: {"off": v.off, "def_": v.def_, "pace": v.pace} for k, v in engine.season_priors.items()},
        "end_season_priors": {
            k: {"off": v.off, "def_": v.def_, "pace": v.pace} for k, v in engine.end_season_priors.items()
        },
        "margin_residuals": engine.margin_residuals[-400:],
        "total_residuals": engine.total_residuals[-400:],
        "_team_index": engine._team_index,
    }


def engine_from_state(raw: dict[str, Any]) -> tuple[V2Engine, set[str], dict[str, float], str | None]:
    params = V2Params()
    engine = V2Engine(params=params, stage=int(raw.get("stage") or 3))
    engine.team_off = {k: float(v) for k, v in (raw.get("team_off") or {}).items()}
    engine.team_def = {k: float(v) for k, v in (raw.get("team_def") or {}).items()}
    engine.team_pace = {k: float(v) for k, v in (raw.get("team_pace") or {}).items()}
    engine.team_games = {k: int(v) for k, v in (raw.get("team_games") or {}).items()}
    engine.margin_residuals = [float(x) for x in raw.get("margin_residuals") or []]
    engine.total_residuals = [float(x) for x in raw.get("total_residuals") or []]
    engine._team_index = {k: int(v) for k, v in (raw.get("_team_index") or {}).items()}

    def _priors(blob: dict[str, Any]) -> dict[str, TeamPrior]:
        out: dict[str, TeamPrior] = {}
        for team, p in blob.items():
            out[team] = TeamPrior(off=float(p["off"]), def_=float(p["def_"]), pace=float(p["pace"]))
        return out

    engine.season_priors = _priors(raw.get("season_priors") or {})
    engine.end_season_priors = _priors(raw.get("end_season_priors") or {})
    processed = set(raw.get("processed_keys") or [])
    poss_cache = {str(k): float(v) for k, v in (raw.get("poss_cache") or {}).items()}
    last_dt = raw.get("last_processed_date")
    return engine, processed, poss_cache, last_dt


def _strip_non_franchise(engine: V2Engine) -> bool:
    """Remove exhibition / international teams from engine dicts. Returns True if anything removed."""
    removed = False

    def _clean(d: dict[str, Any]) -> None:
        nonlocal removed
        for k in list(d.keys()):
            if not is_nba_franchise(k):
                del d[k]
                removed = True

    _clean(engine.team_off)
    _clean(engine.team_def)
    _clean(engine.team_pace)
    _clean(engine.team_games)
    _clean(engine._team_index)
    _clean(engine.season_priors)  # type: ignore[arg-type]
    _clean(engine.end_season_priors)  # type: ignore[arg-type]
    for k in list(engine.player_track.keys()):
        if not is_nba_franchise(k):
            del engine.player_track[k]
            removed = True
    return removed


def _reset_engine_to_committed_priors(engine: V2Engine) -> bool:
    raw = load_committed_priors()
    if not raw:
        return False
    apply_committed_priors(engine, raw)
    engine.history = []
    engine.margin_residuals = []
    engine.total_residuals = []
    engine._cached_off = {}
    engine._cached_def = {}
    engine._refit_cooldown = 0
    return True


def _replay_games(engine: V2Engine, games: list[dict[str, Any]], processed: set[str]) -> date | None:
    last_played: dict[str, datetime] = {}
    team_last_site: dict[str, str] = {}
    team_dates_et: dict[str, list[date]] = {}
    current_season: str | None = None
    max_day: date | None = None

    for g in games:
        key = _game_key(g)
        if key in processed:
            continue
        season = g["season"]
        if current_season and season != current_season:
            committed = load_committed_priors()
            if committed and str(committed.get("for_season") or "") == season:
                apply_committed_priors(engine, committed)
            else:
                engine.end_season()
                engine.start_new_season()
            engine.history = []
            engine._cached_off = {}
            engine._cached_def = {}
        current_season = season

        dt: datetime = g["date"]
        max_day = max(max_day, dt.date()) if max_day else dt.date()
        home, away = g["home"], g["away"]
        hr = _rest_days(home, dt, last_played)
        ar = _rest_days(away, dt, last_played)
        day_et = kickoff_date_et(dt)
        home_3in4 = _three_in_four(home, day_et, team_dates_et)
        away_3in4 = _three_in_four(away, day_et, team_dates_et)
        ctx = {
            "home_rest": hr,
            "away_rest": ar,
            "home_b2b": hr is not None and hr <= 1,
            "away_b2b": ar is not None and ar <= 1,
            "home_3in4": home_3in4,
            "away_3in4": away_3in4,
            "home_travel_mi": travel_miles(team_last_site.get(home, home), home)
            if team_last_site.get(home, home) != home
            else 0.0,
            "away_travel_mi": travel_miles(team_last_site.get(away, away), home)
            if team_last_site.get(away, away) != home
            else 0.0,
        }
        engine.observe(g, ctx=ctx)
        processed.add(key)
        last_played[home] = last_played[away] = dt
        team_last_site[home] = home
        team_last_site[away] = home
        if day_et is not None:
            for t in (home, away):
                team_dates_et.setdefault(t, []).append(day_et)
    return max_day


def _history_row_from_game(
    engine: V2Engine,
    game: dict[str, Any],
    *,
    ctx: dict[str, Any],
) -> HistRow:
    """Build one HistRow without mutating team ratings (projection history only)."""
    home, away = game["home"], game["away"]
    hs, as_ = float(game["home_pts"]), float(game["away_pts"])
    dt: datetime = game["date"]
    poss = float(game.get("game_poss") or game.get("home_poss") or max((hs + as_) / 2.2, 90.0))
    home_ortg = 100.0 * hs / poss
    away_ortg = 100.0 * as_ / poss
    days_w = 1.0
    if engine.history:
        days = max((dt - engine.history[-1].date).days, 1)
        days_w = 0.5 ** (days / max(engine.params.recency_half_life_days, 1.0))
    return HistRow(
        date=dt,
        home=home,
        away=away,
        home_ortg=home_ortg,
        away_ortg=away_ortg,
        pace=poss,
        home_rest=float(ctx.get("home_rest") or 3),
        away_rest=float(ctx.get("away_rest") or 3),
        home_b2b=1.0 if ctx.get("home_b2b") else 0.0,
        away_b2b=1.0 if ctx.get("away_b2b") else 0.0,
        home_3in4=1.0 if ctx.get("home_3in4") else 0.0,
        away_3in4=1.0 if ctx.get("away_3in4") else 0.0,
        home_travel=float(ctx.get("home_travel_mi") or 0),
        away_travel=float(ctx.get("away_travel_mi") or 0),
        home_alt=1.0 if home in ALTITUDE_TEAMS else 0.0,
        away_alt=1.0 if away in ALTITUDE_TEAMS else 0.0,
        weight=days_w,
    )


def rebuild_projection_history(engine: V2Engine, games: list[dict[str, Any]]) -> None:
    """Rebuild in-memory game log for current-season totals (not persisted in state file)."""
    engine.history = []
    last_played: dict[str, datetime] = {}
    team_last_site: dict[str, str] = {}
    team_dates_et: dict[str, list[date]] = {}
    current_season: str | None = None

    for g in sorted(games, key=lambda x: x["date"]):
        season = g["season"]
        if current_season and season != current_season:
            engine.history = []
        current_season = season

        dt: datetime = g["date"]
        home, away = g["home"], g["away"]
        hr = _rest_days(home, dt, last_played)
        ar = _rest_days(away, dt, last_played)
        day_et = kickoff_date_et(dt)
        home_3in4 = _three_in_four(home, day_et, team_dates_et)
        away_3in4 = _three_in_four(away, day_et, team_dates_et)
        ctx = {
            "home_rest": hr,
            "away_rest": ar,
            "home_b2b": hr is not None and hr <= 1,
            "away_b2b": ar is not None and ar <= 1,
            "home_3in4": home_3in4,
            "away_3in4": away_3in4,
            "home_travel_mi": travel_miles(team_last_site.get(home, home), home)
            if team_last_site.get(home, home) != home
            else 0.0,
            "away_travel_mi": travel_miles(team_last_site.get(away, away), home)
            if team_last_site.get(away, away) != home
            else 0.0,
        }
        engine.history.append(_history_row_from_game(engine, g, ctx=ctx))
        last_played[home] = last_played[away] = dt
        team_last_site[home] = home
        team_last_site[away] = home
        if day_et is not None:
            for t in (home, away):
                team_dates_et.setdefault(t, []).append(day_et)


def load_state_file(path: Path | None = None) -> dict[str, Any] | None:
    p = path or STATE_PATH
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def save_state(
    engine: V2Engine,
    processed: set[str],
    *,
    poss_cache: dict[str, float],
    last_processed_date: str | None,
    path: Path | None = None,
) -> None:
    p = path or STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            engine_to_state(
                engine,
                processed=processed,
                poss_cache=poss_cache,
                last_processed_date=last_processed_date,
            ),
            indent=2,
        )
        + "\n"
    )


def _fetch_since(
    *,
    last_processed_date: str | None,
    processed: set[str],
    has_state: bool,
) -> datetime:
    now = datetime.now(timezone.utc)
    if has_state and last_processed_date:
        try:
            ld = date.fromisoformat(last_processed_date)
            return datetime.combine(ld - timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)
        except ValueError:
            pass
    if processed:
        return now - timedelta(days=14)
    return datetime.combine(_season_start_date(now), datetime.min.time(), tzinfo=timezone.utc)


def ensure_score_engine(*, lookback_days: int | None = None) -> V2Engine:
    """Load or bootstrap stage-3 engine from ESPN finals (incremental, event-keyed)."""
    _ = lookback_days  # legacy kw; incremental window derived from state
    raw = load_state_file()
    poss_cache: dict[str, float] = {}
    last_processed_date: str | None = None
    processed: set[str] = set()

    if raw and raw.get("version") in (1, 2):
        engine, processed, poss_cache, last_processed_date = engine_from_state(raw)
        if _strip_non_franchise(engine):
            logger.warning("score engine: dropped non-NBA teams from state — full replay from priors")
            processed = set()
            last_processed_date = None
            if not _reset_engine_to_committed_priors(engine):
                logger.warning("score engine: could not reload committed priors after sanitize")
    else:
        engine = V2Engine(params=V2Params(), stage=3)
        priors = load_committed_priors()
        if priors:
            apply_committed_priors(engine, priors)
        else:
            logger.warning("score engine: no committed priors at %s", PRIORS_PATH)

    since = _fetch_since(
        last_processed_date=last_processed_date,
        processed=processed,
        has_state=raw is not None,
    )
    now = datetime.now(timezone.utc)

    try:
        scores = fetch_espn_nba_finals_by_event(since=since, until=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("score engine: ESPN scores unavailable (%s)", exc)
        scores = []

    games = _games_from_scores(scores, poss_cache=poss_cache)
    before = len(processed)
    max_day = _replay_games(engine, games, processed)
    if max_day:
        last_processed_date = max_day.isoformat()
    if len(processed) > before or not raw:
        save_state(
            engine,
            processed,
            poss_cache=poss_cache,
            last_processed_date=last_processed_date,
        )
        logger.info("score engine: ingested %d new finals", len(processed) - before)

    season_start = datetime.combine(_season_start_date(now), datetime.min.time(), tzinfo=timezone.utc)
    try:
        hist_scores = fetch_espn_nba_finals_by_event(since=season_start, until=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("score engine: season history fetch failed (%s)", exc)
        hist_scores = scores
    hist_games = _games_from_scores(hist_scores, poss_cache=poss_cache)
    rebuild_projection_history(engine, hist_games)
    return engine
