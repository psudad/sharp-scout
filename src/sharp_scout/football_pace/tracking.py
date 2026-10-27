"""Shadow JSON tracking for weekly pace projections (not published)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.data.espn_cfb import fetch_espn_cfb_injuries
from sharp_scout.data.espn_nfl import fetch_espn_nfl_injuries, fetch_espn_nfl_roster
from sharp_scout.football_pace.backtest import summarize_graded, walk_forward_backtest
from sharp_scout.football_pace.config import NCAAF_PACE_CONFIG, NFL_PACE_CONFIG
from sharp_scout.football_pace.engine import PaceEngine
from sharp_scout.football_pace.games import PaceGame, load_ncaaf_games, load_nfl_games
from sharp_scout.football_pace.injury_adjust import project_with_injuries, roster_player_names
from sharp_scout.football_pace.player_value import PlayerValueTracker, attach_nflverse_positions

SHADOW_DIR = DATA_DIR / "shadow" / "football_pace"


def _store_path(sport: str) -> Path:
    return SHADOW_DIR / f"{sport}_pace_projections.json"


def load_store(sport: str) -> dict[str, Any]:
    path = _store_path(sport)
    if not path.exists():
        return {"version": 1, "sport": sport, "projections": [], "summary": {}}
    return json.loads(path.read_text())


def save_store(sport: str, store: dict[str, Any]) -> None:
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    _store_path(sport).write_text(json.dumps(store, indent=2, default=str) + "\n")


def _train_engine_and_tracker(
    games: list[PaceGame], cfg, sport: str
) -> tuple[PaceEngine, PlayerValueTracker]:
    completed = [g for g in games if g.home_score is not None and g.away_score is not None]
    from sharp_scout.football_pace.injury_context import build_injury_context

    seasons = sorted({g.season for g in games})
    ctx = build_injury_context(sport, seasons)
    _, engine = walk_forward_backtest(completed, cfg, injury_ctx=ctx)
    return engine, ctx.tracker


def _live_injuries(sport: str) -> list[dict]:
    if sport == "nfl":
        return fetch_espn_nfl_injuries()
    return fetch_espn_cfb_injuries()


def _team_injuries(all_injuries: list[dict], team: str) -> list[dict]:
    team = team.upper()
    return [r for r in all_injuries if str(r.get("team") or "").upper() == team]


def project_slate(
    sport: str,
    *,
    season: int,
    week: int | None = None,
) -> list[dict[str, Any]]:
    if sport == "nfl":
        cfg = NFL_PACE_CONFIG
        games = load_nfl_games([season])
    else:
        cfg = NCAAF_PACE_CONFIG
        games = load_ncaaf_games([season])

    engine, tracker = _train_engine_and_tracker(games, cfg, sport)
    if sport == "nfl":
        attach_nflverse_positions(tracker)
    injuries = _live_injuries(sport)
    roster_cache: dict[str, list[dict]] = {}

    if week is not None:
        slate = [g for g in games if g.week == week and g.home_score is None]
    else:
        slate = [g for g in games if g.home_score is None]
    out: list[dict[str, Any]] = []
    for g in slate:
        proj = engine.project(g.home, g.away)
        for team in (g.home, g.away):
            if team not in roster_cache:
                if sport == "nfl":
                    roster_cache[team] = fetch_espn_nfl_roster(team)
                    tracker.seed_roster(team, roster_cache[team])
                else:
                    roster_cache[team] = []
        home_inj = _team_injuries(injuries, g.home)
        away_inj = _team_injuries(injuries, g.away)
        for row in home_inj + away_inj:
            tracker.set_position(row["team"], row["player"], row.get("position") or "")
        adj = project_with_injuries(
            proj,
            home_injuries=home_inj,
            away_injuries=away_inj,
            tracker=tracker,
            home_roster=roster_player_names(roster_cache.get(g.home, [])),
            away_roster=roster_player_names(roster_cache.get(g.away, [])),
        )
        spread_edge = proj["margin"] + float(g.spread_home) if g.spread_home is not None else None
        total_edge = proj["total"] - float(g.total_line) if g.total_line is not None else None
        spread_edge_adj = adj["margin"] + float(g.spread_home) if g.spread_home is not None else None
        total_edge_adj = adj["total"] - float(g.total_line) if g.total_line is not None else None
        out.append(
            {
                "season": g.season,
                "week": g.week,
                "game_id": g.game_id,
                "home": g.home,
                "away": g.away,
                "spread_home": g.spread_home,
                "total_line": g.total_line,
                "unadjusted": {
                    "proj_home_pts": round(proj["home_pts"], 2),
                    "proj_away_pts": round(proj["away_pts"], 2),
                    "proj_margin": round(proj["margin"], 2),
                    "proj_total": round(proj["total"], 2),
                    "spread_edge": round(spread_edge, 2) if spread_edge is not None else None,
                    "total_edge": round(total_edge, 2) if total_edge is not None else None,
                    "spread_pick": _pick_side(spread_edge, cfg.min_edge_spread),
                    "total_pick": _pick_ou(total_edge, cfg.min_edge_total),
                },
                "injury_adjusted": {
                    "proj_home_pts": round(adj["home_pts"], 2),
                    "proj_away_pts": round(adj["away_pts"], 2),
                    "proj_margin": round(adj["margin"], 2),
                    "proj_total": round(adj["total"], 2),
                    "spread_edge": round(spread_edge_adj, 2) if spread_edge_adj is not None else None,
                    "total_edge": round(total_edge_adj, 2) if total_edge_adj is not None else None,
                    "spread_pick": _pick_side(spread_edge_adj, cfg.min_edge_spread),
                    "total_pick": _pick_ou(total_edge_adj, cfg.min_edge_total),
                    "home_injuries": home_inj,
                    "away_injuries": away_inj,
                },
            }
        )
    return out


def _pick_side(edge: float | None, min_edge: float) -> str | None:
    if edge is None or abs(edge) < min_edge:
        return None
    return "home" if edge > 0 else "away"


def _pick_ou(edge: float | None, min_edge: float) -> str | None:
    if edge is None or abs(edge) < min_edge:
        return None
    return "over" if edge > 0 else "under"


def record_and_grade_completed(sport: str, season: int) -> dict[str, Any]:
    """Append graded rows for completed games in season to shadow store."""
    from sharp_scout.football_pace.backtest import walk_forward_backtest
    from sharp_scout.football_pace.injury_context import build_injury_context

    if sport == "nfl":
        cfg = NFL_PACE_CONFIG
        games = load_nfl_games([season])
    else:
        cfg = NCAAF_PACE_CONFIG
        games = load_ncaaf_games([season])
    ctx = build_injury_context(sport, [season])
    rows, _ = walk_forward_backtest(games, cfg, injury_ctx=ctx)
    store = load_store(sport)
    existing = {r.get("game_id") for r in store.get("projections") or []}
    for r in rows:
        if r.game_id in existing:
            continue
        store.setdefault("projections", []).append({"game_id": r.game_id, "graded": True, **asdict_row(r)})
    store["summary"] = {
        "unadjusted": summarize_graded(rows, cfg, variant="raw"),
        "injury_adjusted": summarize_graded(rows, cfg, variant="adj"),
    }
    save_store(sport, store)
    return store["summary"]


def asdict_row(r) -> dict:
    from dataclasses import asdict

    return asdict(r)
