"""cfbfastR / sportsdataverse college football play-by-play ingestion."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from sharp_scout.config import DATA_DIR, get_settings
from sharp_scout.data.nflfastr import _download
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / "cfb_pbp_cache"
PBP_URL = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "cfbfastR_cfb_pbp/play_by_play_{season}.parquet"
)
SCHEDULE_URLS = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "cfbfastR_cfb_schedules/cfb_schedules.parquet",
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "cfbfastR_cfb_schedules/schedules.parquet",
)


def _ensure_cache() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def load_cfb_pbp(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load FBS play-by-play; caches parquet locally."""
    settings = get_settings()
    seasons = seasons or settings.seasons
    cache = _ensure_cache()
    frames: list[pd.DataFrame] = []

    for season in seasons:
        path = cache / f"cfb_pbp_{season}.parquet"
        if not path.exists():
            logger.info("Downloading CFB PBP %s from sportsdataverse", season)
            if not _download(PBP_URL.format(season=season), path):
                continue
        try:
            logger.info("Loading CFB PBP %s", season)
            frames.append(pd.read_parquet(path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read CFB PBP %s: %s", season, exc)

    if not frames:
        logger.warning("No CFB PBP frames loaded; returning empty frame")
        return pd.DataFrame()

    return _normalize_cfb_pbp(pd.concat(frames, ignore_index=True))


def _col(df: pd.DataFrame, *names: str) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n in df.columns:
            return n
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _normalize_cfb_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    """Map cfbfastR column variants onto the NFL-style names the ratings engine expects."""
    df = pbp.copy()
    rename: dict[str, str] = {}
    mapping = {
        "posteam": ("posteam", "pos_team", "offense_play", "offense"),
        "defteam": ("defteam", "def_pos_team", "defense_play", "defense"),
        "home_team": ("home_team", "home", "home_id"),
        "away_team": ("away_team", "away", "away_id"),
        "epa": ("epa", "EPA"),
        "success": ("success", "success_play"),
        "yards_gained": ("yards_gained", "yards", "statYardage"),
        "passer_player_name": ("passer_player_name", "passer_name", "pass_player_name"),
        "rusher_player_name": ("rusher_player_name", "rusher_name", "rush_player_name"),
        "qb_dropback": ("qb_dropback", "pass", "is_pass"),
        "play_type": ("play_type", "play_type_nfl", "type_text"),
        "game_date": ("game_date", "start_date", "start_date_time"),
    }
    for dest, cands in mapping.items():
        src = _col(df, *cands)
        if src and src != dest:
            rename[src] = dest
    if rename:
        df = df.rename(columns=rename)

    for col in ("posteam", "defteam", "home_team", "away_team"):
        if col in df.columns:
            df[col] = df[col].astype(str).map(
                lambda x: normalize_team(x, "ncaaf") if x and x != "nan" else x
            )

    cols = [
        "season", "week", "game_id", "play_id", "posteam", "defteam",
        "home_team", "away_team", "passer_player_name", "rusher_player_name",
        "epa", "success", "yards_gained", "pass", "rush", "qb_dropback",
        "down", "play_type", "game_date",
    ]
    present = [c for c in cols if c in df.columns]
    out = df[present].copy()
    if "epa" in out.columns:
        out = out[out["epa"].notna()]
    if "success" not in out.columns and "epa" in out.columns:
        out["success"] = (out["epa"] > 0).astype(float)
    if "yards_gained" not in out.columns:
        out["yards_gained"] = 0.0
    if "qb_dropback" in out.columns:
        out["is_dropback"] = out["qb_dropback"].fillna(0).astype(bool)
    elif "pass" in out.columns:
        out["is_dropback"] = out["pass"].fillna(0).astype(bool)
    else:
        out["is_dropback"] = False
    if "rush" in out.columns:
        out["is_rush"] = out["rush"].fillna(0).astype(bool)
    else:
        out["is_rush"] = ~out["is_dropback"]
    return out.reset_index(drop=True)


def load_cfb_schedules(seasons: list[int] | None = None) -> pd.DataFrame:
    settings = get_settings()
    seasons = seasons or settings.seasons
    cache = _ensure_cache()
    path = cache / "cfb_schedules.parquet"
    if not path.exists():
        logger.info("Downloading CFB schedules from sportsdataverse")
        ok = False
        for url in SCHEDULE_URLS:
            if _download(url, path):
                ok = True
                break
        if not ok:
            return pd.DataFrame()
    try:
        sched = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CFB schedule load failed: %s", exc)
        return pd.DataFrame()

    if "season" in sched.columns:
        sched = sched[sched["season"].isin(seasons)]
    for dest, cands in (
        ("home_team", ("home_team", "home")),
        ("away_team", ("away_team", "away")),
        ("home_score", ("home_score", "home_points", "home_team_score")),
        ("away_score", ("away_score", "away_points", "away_team_score")),
        ("week", ("week", "week_num", "game_week")),
        ("game_id", ("game_id", "id", "game_id_std")),
    ):
        src = _col(sched, *cands)
        if src and src != dest:
            sched = sched.rename(columns={src: dest})
    for col in ("home_team", "away_team"):
        if col in sched.columns:
            sched[col] = sched[col].astype(str).map(lambda x: normalize_team(x, "ncaaf"))
    return sched.reset_index(drop=True)
