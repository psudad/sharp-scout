"""Load game slates with lines and scores (free sources only)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

from sharp_scout.data.cfbfastr import fbs_teams, load_cfb_pbp
from sharp_scout.data.nflfastr import load_pbp, load_schedules
from sharp_scout.football_pace.lines import cfb_pbp_home_spread, nflverse_home_spread
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

Sport = Literal["nfl", "ncaaf"]


@dataclass(frozen=True)
class PaceGame:
    sport: Sport
    season: int
    week: int
    game_id: str
    game_date: datetime | None
    home: str
    away: str
    home_score: float | None
    away_score: float | None
    spread_home: float | None
    total_line: float | None
    home_plays: float | None = None
    away_plays: float | None = None


def _parse_gameday(val) -> datetime | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        ts = pd.Timestamp(val)
        if ts.tzinfo is None:
            return ts.to_pydatetime().replace(tzinfo=datetime.now().astimezone().tzinfo)
        return ts.to_pydatetime()
    except Exception:  # noqa: BLE001
        return None


def load_nfl_games(
    seasons: list[int],
    *,
    game_types: tuple[str, ...] = ("REG", "POST"),
) -> list[PaceGame]:
    sched = load_schedules(seasons)
    if sched.empty:
        return []
    if "game_type" in sched.columns:
        sched = sched[sched["game_type"].isin(game_types)]
    pbp = load_pbp(seasons)
    play_counts = _nfl_play_counts_by_game(pbp)

    games: list[PaceGame] = []
    for row in sched.itertuples():
        gid = str(getattr(row, "game_id", "") or "")
        pc = play_counts.get(gid, {})
        hs = getattr(row, "home_score", None)
        aw = getattr(row, "away_score", None)
        spread = nflverse_home_spread(getattr(row, "spread_line", None))
        total = getattr(row, "total_line", None)
        total_f = float(total) if total is not None and pd.notna(total) else None
        games.append(
            PaceGame(
                sport="nfl",
                season=int(row.season),
                week=int(row.week),
                game_id=gid,
                game_date=_parse_gameday(getattr(row, "gameday", None)),
                home=str(row.home_team),
                away=str(row.away_team),
                home_score=float(hs) if hs is not None and pd.notna(hs) else None,
                away_score=float(aw) if aw is not None and pd.notna(aw) else None,
                spread_home=spread,
                total_line=total_f,
                home_plays=pc.get("home_plays"),
                away_plays=pc.get("away_plays"),
            )
        )
    games.sort(key=lambda g: (g.season, g.week, g.game_date or datetime.min, g.game_id))
    return games


def _nfl_play_counts_by_game(pbp: pd.DataFrame) -> dict[str, dict[str, float]]:
    from sharp_scout.football_pace.pbp_stats import build_game_play_counts

    if pbp.empty:
        return {}
    out: dict[str, dict[str, float]] = {}
    gdf = build_game_play_counts(pbp, wp_col="wp" if "wp" in pbp.columns else "wp_before")
    for r in gdf.itertuples():
        out[str(r.game_id)] = {"home_plays": float(r.home_plays), "away_plays": float(r.away_plays)}
    return out


def load_ncaaf_games(seasons: list[int], *, fbs_only: bool = True) -> list[PaceGame]:
    """Games from cfbfastR PBP (includes ``spread`` / ``over_under`` on each row)."""
    from sharp_scout.config import DATA_DIR
    from sharp_scout.football_pace.pbp_stats import build_game_play_counts

    cache_dir = DATA_DIR / "cfb_pbp_cache"
    fbs: set[str] = set()
    games: list[PaceGame] = []

    norm = load_cfb_pbp(seasons)
    if norm.empty:
        return []
    fbs |= fbs_teams(norm)
    play_map = {
        str(r.game_id): (float(r.home_plays), float(r.away_plays))
        for r in build_game_play_counts(norm, wp_col="wp_before").itertuples()
    }

    meta_cols = (
        "game_id",
        "season",
        "week",
        "home_team",
        "away_team",
        "spread",
        "over_under",
        "completed",
        "pos_team",
        "pos_team_score",
        "start_date",
    )

    for season in seasons:
        path = cache_dir / f"cfb_pbp_{season}.parquet"
        if not path.exists():
            logger.info("Loading CFB PBP %s via loader", season)
            load_cfb_pbp([season])
            if not path.exists():
                continue
        import pyarrow.parquet as pq

        avail = set(pq.read_schema(path).names)
        use_cols = [c for c in meta_cols if c in avail]
        raw = pd.read_parquet(path, columns=use_cols)
        if raw.empty:
            continue

        meta = raw.groupby("game_id", sort=False).agg(
            season=("season", "first"),
            week=("week", "first"),
            home_team=("home_team", "first"),
            away_team=("away_team", "first"),
            spread=("spread", "first"),
            over_under=("over_under", "first"),
            completed=("completed", "first"),
            start_date=("start_date", "first"),
        )
        score = raw.dropna(subset=["pos_team", "pos_team_score"]).copy()
        score["is_home"] = score["pos_team"].astype(str) == score["home_team"].astype(str)
        score["is_away"] = score["pos_team"].astype(str) == score["away_team"].astype(str)
        home_sc = score.loc[score["is_home"]].groupby("game_id")["pos_team_score"].max()
        away_sc = score.loc[score["is_away"]].groupby("game_id")["pos_team_score"].max()

        for gid, row in meta.iterrows():
            home_c = normalize_team(str(row.home_team), "ncaaf")
            away_c = normalize_team(str(row.away_team), "ncaaf")
            if fbs_only and fbs and (home_c not in fbs or away_c not in fbs):
                continue
            spread = cfb_pbp_home_spread(row.spread) if pd.notna(row.spread) else None
            total = float(row.over_under) if pd.notna(row.over_under) else None
            completed = bool(row.completed) if pd.notna(row.completed) else True
            hs = float(home_sc.get(gid)) if completed and gid in home_sc.index else None
            aw = float(away_sc.get(gid)) if completed and gid in away_sc.index else None
            hp, ap = play_map.get(str(gid), (None, None))
            games.append(
                PaceGame(
                    sport="ncaaf",
                    season=int(row.season),
                    week=int(row.week),
                    game_id=str(gid),
                    game_date=_parse_gameday(row.start_date),
                    home=home_c,
                    away=away_c,
                    home_score=hs,
                    away_score=aw,
                    spread_home=spread,
                    total_line=total,
                    home_plays=hp,
                    away_plays=ap,
                )
            )

    games.sort(key=lambda g: (g.season, g.week, g.game_date or datetime.min, g.game_id))
    return games


def upcoming_nfl_week(season: int, week: int) -> list[PaceGame]:
    games = load_nfl_games([season])
    return [g for g in games if g.week == week and g.home_score is None and g.away_score is None]


def upcoming_ncaaf_week(season: int, week: int) -> list[PaceGame]:
    games = load_ncaaf_games([season])
    return [g for g in games if g.week == week and g.home_score is None and g.away_score is None]
