"""Drive-level table from 2026 cfbfastR PBP."""

from __future__ import annotations

import pandas as pd

from sharp_scout.data.cfbfastr import load_cfb_pbp
from sharp_scout.utils.odds import normalize_team

DRIVE_COLS = (
    "game_id",
    "drive_id",
    "drive_number",
    "drive_result",
    "drive_pts",
    "drive_start_yards_to_goal",
    "drive_yards",
    "drive_time_seconds_elapsed",
    "drive_play_number",
    "pos_team",
    "def_pos_team",
    "home_team",
    "away_team",
    "season",
    "week",
    "completed",
    "home_score",
    "away_score",
    "pos_team_score",
)

RESULT_MAP = {
    "TD": "td",
    "FG": "fg",
    "MISSED FG": "miss_fg",
    "PUNT": "punt",
    "INT": "int",
    "FUMBLE": "fumble",
    "DOWNS": "downs",
    "END OF HALF": "end_half",
    "END OF GAME": "end_game",
    "INT TD": "int",
    "FUMBLE RETURN TD": "fumble",
    "FUMBLE TD": "fumble",
    "PUNT TD": "punt",
    "SF": "downs",
}


def _canonical_result(raw: str) -> str:
    key = (raw or "").strip().upper()
    return RESULT_MAP.get(key, "other")


def load_drive_table(season: int = 2026) -> pd.DataFrame:
    pbp = load_cfb_pbp([season])
    if pbp.empty:
        return pd.DataFrame()
    import pyarrow.parquet as pq
    from sharp_scout.config import DATA_DIR

    path = DATA_DIR / "cfb_pbp_cache" / f"cfb_pbp_{season}.parquet"
    avail = set(pq.read_schema(path).names)
    use = [c for c in DRIVE_COLS if c in avail]
    raw = pd.read_parquet(path, columns=use)
    if "drive_id" not in raw.columns:
        return pd.DataFrame()

    # One row per drive: first offensive snap row (min drive_play_number)
    raw = raw[raw["drive_id"].notna()].copy()
    if "drive_play_number" in raw.columns:
        idx = raw.groupby(["game_id", "drive_id"])["drive_play_number"].idxmin()
        drives = raw.loc[idx].copy()
    else:
        drives = raw.drop_duplicates(["game_id", "drive_id"]).copy()

    for col in ("pos_team", "def_pos_team", "home_team", "away_team"):
        if col in drives.columns:
            drives[col] = drives[col].apply(
                lambda x: normalize_team(str(x), "ncaaf")
                if pd.notna(x) and str(x).lower() not in ("nan", "none", "")
                else ""
            )

    drives["offense"] = drives["pos_team"]
    drives["defense"] = drives["def_pos_team"]
    drives["result"] = drives["drive_result"].map(lambda x: _canonical_result(str(x)))
    drives["start_ytg"] = pd.to_numeric(drives["drive_start_yards_to_goal"], errors="coerce")
    drives["pts"] = pd.to_numeric(drives["drive_pts"], errors="coerce").fillna(0)
    drives["plays"] = pd.to_numeric(
        drives.get("drive_play_number"), errors="coerce"
    ).fillna(6)
    drives["sec"] = pd.to_numeric(
        drives.get("drive_time_seconds_elapsed"), errors="coerce"
    ).fillna(120)

    if "completed" in drives.columns:
        drives = drives[drives["completed"].astype(bool)]
    if "home_score" in raw.columns and "away_score" in raw.columns:
        scores = raw.groupby("game_id").agg(home_score=("home_score", "max"), away_score=("away_score", "max"))
        drives = drives.drop(columns=[c for c in ("home_score", "away_score") if c in drives.columns], errors="ignore")
        drives = drives.merge(scores, on="game_id", how="left")
    elif "pos_team_score" in raw.columns and "home_team" in raw.columns:
        sc = raw.dropna(subset=["pos_team", "pos_team_score"]).copy()
        sc["is_home"] = sc["pos_team"].astype(str) == sc["home_team"].astype(str)
        home_sc = sc.loc[sc["is_home"]].groupby("game_id")["pos_team_score"].max()
        away_sc = sc.loc[~sc["is_home"]].groupby("game_id")["pos_team_score"].max()
        scores = pd.DataFrame({"home_score": home_sc, "away_score": away_sc}).reset_index()
        drives = drives.merge(scores, on="game_id", how="left")
    drives = drives[drives["result"].isin({"td", "fg", "miss_fg", "punt", "int", "fumble", "downs", "end_half", "end_game", "other"})]
    return drives.reset_index(drop=True)


def season_actual_scoring(drives: pd.DataFrame) -> dict[str, float]:
    """Mean team points and total from completed 2026 games in drive table."""
    if drives.empty:
        return {"team_pts_mean": 0.0, "total_mean": 0.0}
    games = drives.groupby("game_id").agg(
        home=("home_team", "first"),
        away=("away_team", "first"),
        home_score=("home_score", "max"),
        away_score=("away_score", "max"),
    )
    games = games.dropna(subset=["home_score", "away_score"])
    if games.empty:
        return {"team_pts_mean": 0.0, "total_mean": 0.0}
    team_pts = list(games["home_score"]) + list(games["away_score"])
    totals = games["home_score"] + games["away_score"]
    return {
        "team_pts_mean": float(sum(team_pts) / len(team_pts)),
        "total_mean": float(totals.mean()),
        "games": int(len(games)),
    }
