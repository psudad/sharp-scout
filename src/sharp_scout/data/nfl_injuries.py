"""nflverse weekly injury reports (free, historical + in-season)."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pandas as pd

from sharp_scout.config import DATA_DIR
from sharp_scout.data.nflfastr import _download
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / "pbp_cache"
INJ_URL = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.parquet"

ACTIVE_STATUSES = frozenset({"Out", "Doubtful", "Questionable"})


def load_nfl_injuries(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load official report_status rows for given seasons."""
    seasons = seasons or []
    frames: list[pd.DataFrame] = []
    cache = CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    for season in seasons:
        path = cache / f"injuries_{season}.parquet"
        if not path.exists():
            logger.info("Downloading nflverse injuries %s", season)
            if not _download(INJ_URL.format(season=season), path):
                continue
        try:
            df = pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("injuries %s read failed: %s", season, exc)
            continue
        if "team" in df.columns:
            df["team"] = df["team"].map(lambda t: normalize_team(str(t), "nfl"))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if "report_status" in out.columns:
        out = out[out["report_status"].isin(ACTIVE_STATUSES)]
    return out.reset_index(drop=True)


def injuries_for_team_week(
    injuries: pd.DataFrame,
    *,
    season: int,
    week: int,
    team: str,
) -> list[dict]:
    if injuries.empty:
        return []
    team = normalize_team(team, "nfl")
    sub = injuries[
        (injuries["season"] == season)
        & (injuries["week"] == week)
        & (injuries["team"] == team)
    ]
    rows: list[dict] = []
    for r in sub.itertuples():
        rows.append(
            {
                "player": str(getattr(r, "full_name", "") or ""),
                "team": team,
                "position": str(getattr(r, "position", "") or ""),
                "status": str(getattr(r, "report_status", "") or ""),
                "injury": str(getattr(r, "report_primary_injury", "") or ""),
            }
        )
    return rows
