"""Persist / restore live V2 score engine from ESPN-backed game history."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.data.espn_nba import fetch_espn_nba_scores
from sharp_scout.nba.score_model.engine import V2Engine, V2Params
from sharp_scout.nba.score_model.teams_geo import travel_miles
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc

logger = logging.getLogger(__name__)

STATE_PATH = DATA_DIR / "paper" / "nba_score_model_state.json"
LEAGUE_PPP = 112.0 / 100.0


def _season_label(dt: datetime) -> str:
    y = dt.year
    if dt.month >= 10:
        return f"{y}-{(y + 1) % 100:02d}"
    return f"{y - 1}-{y % 100:02d}"


def _game_key(g: dict[str, Any]) -> str:
    d = g.get("date")
    ds = d.date().isoformat() if isinstance(d, datetime) else str(d)
    return f"{g['away']}@{g['home']}@{ds}"


def _estimate_poss(hs: float, as_: float) -> float:
    return max((hs + as_) / 2.2, 90.0)


def _rest_days(team: str, dt: datetime, last: dict[str, datetime]) -> int | None:
    prev = last.get(team)
    if prev is None:
        return None
    return max((dt.date() - prev.date()).days, 0)


def _games_from_scores(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in scores:
        kick = parse_kickoff_utc(row.get("kickoff")) or datetime.now(timezone.utc)
        hs, as_ = float(row["home_score"]), float(row["away_score"])
        home = normalize_nba_team(str(row["home_team"]))
        away = normalize_nba_team(str(row["away_team"]))
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
                "event_id": row.get("event_id"),
            }
        )
    out.sort(key=lambda g: g["date"])
    return out


def engine_to_state(engine: V2Engine, *, processed: set[str]) -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stage": engine.stage,
        "processed_keys": sorted(processed),
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


def engine_from_state(raw: dict[str, Any]) -> tuple[V2Engine, set[str]]:
    from sharp_scout.nba.score_model.engine import TeamPrior

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
    return engine, processed


def _replay_games(engine: V2Engine, games: list[dict[str, Any]], processed: set[str]) -> None:
    last_played: dict[str, datetime] = {}
    team_last_site: dict[str, str] = {}
    team_dates: dict[str, list[datetime]] = {}
    current_season: str | None = None

    for g in games:
        key = _game_key(g)
        if key in processed:
            continue
        season = g["season"]
        if current_season and season != current_season:
            engine.end_season()
            engine.start_new_season()
        current_season = season

        dt: datetime = g["date"]
        home, away = g["home"], g["away"]
        hr = _rest_days(home, dt, last_played)
        ar = _rest_days(away, dt, last_played)
        cutoff = dt - timedelta(days=4)
        home_3in4 = sum(1 for d in team_dates.get(home, []) if cutoff < d < dt) >= 2
        away_3in4 = sum(1 for d in team_dates.get(away, []) if cutoff < d < dt) >= 2
        ctx = {
            "home_rest": hr,
            "away_rest": ar,
            "home_b2b": hr is not None and hr <= 1,
            "away_b2b": ar is not None and ar <= 1,
            "home_3in4": home_3in4,
            "away_3in4": away_3in4,
            "home_travel_mi": travel_miles(team_last_site.get(home, home), home) if team_last_site.get(home, home) != home else 0.0,
            "away_travel_mi": travel_miles(team_last_site.get(away, away), away) if team_last_site.get(away, away) != away else 0.0,
        }
        engine.observe(g, ctx=ctx)
        processed.add(key)
        last_played[home] = last_played[away] = dt
        team_last_site[home] = home
        team_last_site[away] = away
        team_dates.setdefault(home, []).append(dt)
        team_dates.setdefault(away, []).append(dt)


def load_state_file(path: Path | None = None) -> dict[str, Any] | None:
    p = path or STATE_PATH
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def save_state(engine: V2Engine, processed: set[str], path: Path | None = None) -> None:
    p = path or STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(engine_to_state(engine, processed=processed), indent=2) + "\n")


def ensure_score_engine(*, lookback_days: int = 100) -> V2Engine:
    """Load or bootstrap stage-3 engine from ESPN finals (free)."""
    raw = load_state_file()
    processed: set[str] = set()
    if raw and raw.get("version") == 1:
        engine, processed = engine_from_state(raw)
    else:
        engine = V2Engine(params=V2Params(), stage=3)

    try:
        scores = fetch_espn_nba_scores(lookback_days=lookback_days)
    except Exception as exc:  # noqa: BLE001
        logger.warning("score engine: ESPN scores unavailable (%s)", exc)
        scores = []

    games = _games_from_scores(scores)
    before = len(processed)
    _replay_games(engine, games, processed)
    if len(processed) > before:
        save_state(engine, processed)
        logger.info("score engine: ingested %d new finals", len(processed) - before)
    elif not raw:
        save_state(engine, processed)
    return engine
