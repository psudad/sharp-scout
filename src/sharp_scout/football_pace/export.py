"""Build weekly slate rows and write shadow JSON/CSV artifacts."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.football_pace.config import NCAAF_PACE_CONFIG, NFL_PACE_CONFIG
from sharp_scout.football_pace.games import PaceGame, load_ncaaf_games, load_nfl_games
from sharp_scout.football_pace.pipeline import project_game, signal_label
from sharp_scout.football_pace.tracking import (
    SHADOW_DIR,
    _live_injuries,
    _team_injuries,
    _train_engine_and_tracker,
)
from sharp_scout.data.espn_nfl import fetch_espn_nfl_roster
from sharp_scout.football_pace.injury_adjust import roster_player_names
from sharp_scout.football_pace.player_value import attach_nflverse_positions


def _cfb_team_id_name_map(season: int) -> dict[str, str]:
    """Map cfbfastR team ids → normalized team codes from rows that include names."""
    import pandas as pd
    import pyarrow.parquet as pq

    from sharp_scout.config import DATA_DIR
    from sharp_scout.utils.odds import normalize_team

    mapping: dict[str, str] = {}
    for yr in range(season - 2, season + 1):
        path = DATA_DIR / "cfb_pbp_cache" / f"cfb_pbp_{yr}.parquet"
        if not path.exists():
            continue
        cols = set(pq.read_schema(path).names)
        need = [c for c in ("home_team", "away_team", "home_team_id", "away_team_id") if c in cols]
        if len(need) < 4:
            continue
        raw = pd.read_parquet(path, columns=need)
        for side in ("home", "away"):
            tid_col = f"{side}_team_id"
            tname = f"{side}_team"
            for tid, name in zip(raw[tid_col], raw[tname]):
                if pd.isna(tid) or pd.isna(name):
                    continue
                try:
                    key = str(int(float(tid)))
                except (TypeError, ValueError):
                    key = str(tid)
                if key not in mapping:
                    mapping[key] = normalize_team(str(name), "ncaaf")
    return mapping


def _enrich_ncaaf_teams(games: list[PaceGame], season: int, week: int) -> list[PaceGame]:
    from dataclasses import replace

    import pandas as pd
    import pyarrow.parquet as pq

    from sharp_scout.config import DATA_DIR
    from sharp_scout.data.espn_cfb import fetch_espn_cfb_week_slate

    slate = fetch_espn_cfb_week_slate(season, week)
    id_map = _cfb_team_id_name_map(season)
    gid_ids: dict[str, tuple[str, str]] = {}
    path = DATA_DIR / "cfb_pbp_cache" / f"cfb_pbp_{season}.parquet"
    if path.exists():
        cols = set(pq.read_schema(path).names)
        if {"game_id", "home_team_id", "away_team_id"}.issubset(cols):
            meta = pd.read_parquet(path, columns=["game_id", "home_team_id", "away_team_id"])
            meta = meta.drop_duplicates("game_id")
            for row in meta.itertuples():
                gid_ids[str(row.game_id)] = (str(row.home_team_id), str(row.away_team_id))

    out: list[PaceGame] = []
    for g in games:
        home, away = g.home, g.away
        if home in ("NAN", "nan", "") or away in ("NAN", "nan", ""):
            meta = slate.get(str(g.game_id))
            if meta:
                home, away = meta["home_team"], meta["away_team"]
            else:
                hid, aid = gid_ids.get(str(g.game_id), ("", ""))
                if home in ("NAN", "nan", "") and hid:
                    try:
                        hk = str(int(float(hid)))
                    except (TypeError, ValueError):
                        hk = hid.split(".")[0]
                    home = id_map.get(hk, home)
                if away in ("NAN", "nan", "") and aid:
                    try:
                        ak = str(int(float(aid)))
                    except (TypeError, ValueError):
                        ak = aid.split(".")[0]
                    away = id_map.get(ak, away)
            if home not in ("NAN", "nan", "") and away not in ("NAN", "nan", ""):
                g = replace(g, home=home, away=away)
        out.append(g)
    return out


def games_for_week(sport: str, season: int, week: int) -> list[PaceGame]:
    if sport == "nfl":
        games = load_nfl_games([season])
    else:
        games = load_ncaaf_games([season], fbs_only=False)
        games = [g for g in games if g.spread_home is not None and g.total_line is not None]
        games = _enrich_ncaaf_teams(games, season, week)
    return [g for g in games if g.week == week]


def _side_pick(edge: float | None, min_edge: float) -> str | None:
    if edge is None or abs(edge) < min_edge:
        return None
    return "home" if edge > 0 else "away"


def _ou_pick(edge: float | None, min_edge: float) -> str | None:
    if edge is None or abs(edge) < min_edge:
        return None
    return "over" if edge > 0 else "under"


def _view(proj: dict[str, float], g: PaceGame, cfg) -> dict[str, Any]:
    se = proj["margin"] + float(g.spread_home) if g.spread_home is not None else None
    te = proj["total"] - float(g.total_line) if g.total_line is not None else None
    return {
        "home_pts": round(proj["home_pts"], 2),
        "away_pts": round(proj["away_pts"], 2),
        "margin": round(proj["margin"], 2),
        "total": round(proj["total"], 2),
        "spread_edge": round(se, 2) if se is not None else None,
        "total_edge": round(te, 2) if te is not None else None,
        "spread_signal": signal_label(se, cfg.min_edge_spread, cfg.lean_min_edge_spread),
        "total_signal": signal_label(te, cfg.min_edge_total, cfg.lean_min_edge_total),
        "spread_pick": _side_pick(se, cfg.min_edge_spread),
        "total_pick": _ou_pick(te, cfg.min_edge_total),
    }


def build_week_rows(sport: str, season: int, week: int) -> list[dict[str, Any]]:
    cfg = NFL_PACE_CONFIG if sport == "nfl" else NCAAF_PACE_CONFIG
    games = games_for_week(sport, season, week)
    train_seasons = sorted({season, season - 1})
    all_games = load_nfl_games(train_seasons) if sport == "nfl" else load_ncaaf_games(train_seasons, fbs_only=False)
    engine, tracker = _train_engine_and_tracker(all_games, cfg, sport)
    if sport == "nfl":
        attach_nflverse_positions(tracker)
    injuries = _live_injuries(sport)
    roster_cache: dict[str, list[dict]] = {}
    rows: list[dict[str, Any]] = []
    for g in games:
        for team in (g.home, g.away):
            if sport == "nfl" and team not in roster_cache:
                roster_cache[team] = fetch_espn_nfl_roster(team)
                tracker.seed_roster(team, roster_cache[team])
        home_inj = _team_injuries(injuries, g.home)
        away_inj = _team_injuries(injuries, g.away)
        for row in home_inj + away_inj:
            tracker.set_position(row["team"], row["player"], row.get("position") or "")
        raw = engine.project(g.home, g.away)
        blended, adj = project_game(
            engine,
            g,
            cfg,
            tracker=tracker,
            live_home_inj=home_inj,
            live_away_inj=away_inj,
            home_roster=roster_player_names(roster_cache.get(g.home, [])),
            away_roster=roster_player_names(roster_cache.get(g.away, [])),
        )
        adj = adj or blended

        rows.append(
            {
                "sport": sport,
                "season": season,
                "week": week,
                "game_id": g.game_id,
                "home": g.home,
                "away": g.away,
                "spread_home": g.spread_home,
                "total_line": g.total_line,
                "kickoff": g.game_date.isoformat() if g.game_date else None,
                "status": "final" if g.home_score is not None else "scheduled",
                "model_raw": {
                    "home_pts": round(raw["home_pts"], 2),
                    "away_pts": round(raw["away_pts"], 2),
                    "margin": round(raw["margin"], 2),
                    "total": round(raw["total"], 2),
                },
                "unadjusted": _view(blended, g, cfg),
                "injury_adjusted": _view(adj, g, cfg),
                "injury_adjusted_meta": {
                    "home_injuries": home_inj,
                    "away_injuries": away_inj,
                },
            }
        )
    return rows


def write_week_artifacts(
    *,
    season: int,
    nfl_week: int | None,
    ncaaf_week: int | None,
) -> dict[str, Any]:
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "nfl_week": nfl_week,
        "ncaaf_week": ncaaf_week,
    }
    all_rows: list[dict[str, Any]] = []
    if nfl_week is not None:
        all_rows.extend(build_week_rows("nfl", season, nfl_week))
    if ncaaf_week is not None:
        all_rows.extend(build_week_rows("ncaaf", season, ncaaf_week))
    json_path = SHADOW_DIR / f"week_{season}_projections.json"
    csv_path = SHADOW_DIR / f"week_{season}_projections.csv"
    payload = {**meta, "games": all_rows}
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    if all_rows:
        csv_rows = []
        for r in all_rows:
            flat = {k: r[k] for k in r if k not in ("unadjusted", "injury_adjusted", "injury_adjusted_meta", "model_raw")}
            for side in ("unadjusted", "injury_adjusted"):
                block = r.get(side) or {}
                for k, v in block.items():
                    flat[f"{side}_{k}"] = v
            csv_rows.append(flat)
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(csv_rows)
    meta["json"] = str(json_path.relative_to(DATA_DIR))
    meta["csv"] = str(csv_path.relative_to(DATA_DIR))
    meta["game_count"] = len(all_rows)
    return meta
