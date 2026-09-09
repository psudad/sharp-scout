"""nflverse play-by-play ingestion (direct parquet; no nfl-data-py)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx
import pandas as pd

from sharp_scout.config import DATA_DIR, get_settings
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / "pbp_cache"
PBP_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/pbp/"
    "play_by_play_{season}.parquet"
)
SCHEDULE_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet"
)
PLAYERS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet"
)
# Roster moves make a stale players.parquet actively wrong, so re-download daily.
PLAYERS_MAX_AGE_HOURS = 24.0


def _ensure_cache() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def _download(url: str, dest: Path) -> bool:
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    logger.warning("Download failed %s → %s", url, resp.status_code)
                    return False
                with dest.open("wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Download error %s: %s", url, exc)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def load_pbp(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load play-by-play for seasons; caches parquet locally."""
    settings = get_settings()
    seasons = seasons or settings.seasons
    cache = _ensure_cache()
    frames: list[pd.DataFrame] = []

    for season in seasons:
        path = cache / f"pbp_{season}.parquet"
        if not path.exists():
            logger.info("Downloading PBP %s from nflverse", season)
            ok = _download(PBP_URL.format(season=season), path)
            if not ok:
                continue
        try:
            logger.info("Loading PBP %s", season)
            frames.append(pd.read_parquet(path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read PBP %s: %s", season, exc)

    if not frames:
        logger.warning("No PBP frames loaded; returning empty frame")
        return pd.DataFrame()

    return _normalize_pbp(pd.concat(frames, ignore_index=True))


def _normalize_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "season",
        "week",
        "game_id",
        "play_id",
        "posteam",
        "defteam",
        "home_team",
        "away_team",
        "passer_player_name",
        "passer_player_id",
        "rusher_player_name",
        "rusher_player_id",
        # Receiving columns are required by the player-props usage engine.
        "receiver_player_name",
        "receiver_player_id",
        "complete_pass",
        "air_yards",
        "epa",
        "success",
        "yards_gained",
        # Per-discipline yardage is cleaner than yards_gained (which mixes sacks/YAC).
        "passing_yards",
        "receiving_yards",
        "rushing_yards",
        "touchdown",
        "pass_touchdown",
        "rush_touchdown",
        "yardline_100",
        "cpoe",
        "sack",
        "pass",
        "rush",
        "qb_dropback",
        "down",
        "play_type",
        "fixed_drive",
        "game_date",
        "spread_line",
        "total_line",
        "roof",
        "temp",
        "wind",
    ]
    present = [c for c in cols if c in pbp.columns]
    df = pbp[present].copy()

    if "play_type" in df.columns:
        df = df[
            df["play_type"].isin(["pass", "run", "qb_kneel", "qb_spike"])
            | df["play_type"].isna()
        ]
    if "epa" in df.columns:
        df = df[df["epa"].notna()]

    for col in ("posteam", "defteam", "home_team", "away_team"):
        if col in df.columns:
            df[col] = df[col].map(
                lambda x: normalize_team(x) if isinstance(x, str) and x.strip() else x
            )

    if "success" not in df.columns and "epa" in df.columns:
        df["success"] = (df["epa"] > 0).astype(float)
    if "yards_gained" not in df.columns:
        df["yards_gained"] = 0.0

    if "qb_dropback" in df.columns:
        df["is_dropback"] = df["qb_dropback"].fillna(0).astype(bool)
    elif "pass" in df.columns:
        df["is_dropback"] = df["pass"].fillna(0).astype(bool)
    else:
        df["is_dropback"] = False

    if "rush" in df.columns:
        df["is_rush"] = df["rush"].fillna(0).astype(bool)
    else:
        df["is_rush"] = ~df["is_dropback"]

    return df.reset_index(drop=True)


def load_players() -> pd.DataFrame:
    """nflverse player directory — gsis_id → display name, position, current team.

    PBP only carries abbreviated names ("J.Smith-Njigba") and no position, so this is
    what lets props match sportsbook player names and resolve the team a player is on
    *now* rather than the team he happened to play for in an older season.
    """
    cache = _ensure_cache()
    path = cache / "players.parquet"
    stale = True
    if path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        stale = age_h > PLAYERS_MAX_AGE_HOURS
    if stale:
        logger.info("Downloading players.parquet from nflverse")
        if not _download(PLAYERS_URL, path) and not path.exists():
            return pd.DataFrame()
    try:
        players = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Players load failed: %s", exc)
        return pd.DataFrame()

    keep = [
        c
        for c in ("gsis_id", "display_name", "football_name", "position", "position_group", "latest_team", "status", "last_season")
        if c in players.columns
    ]
    if "gsis_id" not in keep or "display_name" not in keep:
        logger.warning("players.parquet missing gsis_id/display_name — ignoring")
        return pd.DataFrame()
    out = players[keep].copy()
    out = out[out["gsis_id"].notna()]
    if "latest_team" in out.columns:
        out["latest_team"] = out["latest_team"].map(
            lambda x: normalize_team(x) if isinstance(x, str) and x.strip() else None
        )
    return out.reset_index(drop=True)


def load_schedules(seasons: list[int] | None = None) -> pd.DataFrame:
    settings = get_settings()
    seasons = seasons or settings.seasons
    cache = _ensure_cache()
    path = cache / "schedules.parquet"
    if not path.exists():
        logger.info("Downloading schedules from nflverse")
        if not _download(SCHEDULE_URL, path):
            return pd.DataFrame()
    try:
        sched = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Schedule load failed: %s", exc)
        return pd.DataFrame()

    if "season" in sched.columns:
        sched = sched[sched["season"].isin(seasons)]
    for col in ("home_team", "away_team"):
        if col in sched.columns:
            sched[col] = sched[col].map(
                lambda x: normalize_team(x) if isinstance(x, str) and x.strip() else x
            )
    return sched.reset_index(drop=True)