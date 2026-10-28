"""Derive per-game offensive play counts and filter garbage-time snaps."""

from __future__ import annotations

import pandas as pd

GARBAGE_WP = (0.05, 0.95)


def _scrimmage_mask(df: pd.DataFrame) -> pd.Series:
    if "is_rush" in df.columns and "is_dropback" in df.columns:
        return df["is_rush"].astype(bool) | df["is_dropback"].astype(bool)
    if "play_type" in df.columns:
        return df["play_type"].isin(["pass", "run", "qb_kneel", "qb_spike"])
    return pd.Series(True, index=df.index)


def filter_rating_plays(df: pd.DataFrame, *, wp_col: str = "wp") -> pd.DataFrame:
    out = df.loc[_scrimmage_mask(df)].copy()
    if wp_col in out.columns:
        wp = pd.to_numeric(out[wp_col], errors="coerce")
        lo, hi = GARBAGE_WP
        out = out[wp.isna() | ((wp > lo) & (wp < hi))]
    elif "wp_before" in out.columns:
        wp = pd.to_numeric(out["wp_before"], errors="coerce")
        lo, hi = GARBAGE_WP
        out = out[wp.isna() | ((wp > lo) & (wp < hi))]
    return out


def team_offensive_plays_in_game(
    game_plays: pd.DataFrame,
    *,
    team: str,
    posteam_col: str = "posteam",
) -> float:
    if game_plays.empty or posteam_col not in game_plays.columns:
        return 0.0
    return float((game_plays[posteam_col] == team).sum())


def build_game_play_counts(pbp: pd.DataFrame, *, wp_col: str = "wp") -> pd.DataFrame:
    """One row per game_id with home/away offensive play counts (post-filter)."""
    if pbp.empty or "game_id" not in pbp.columns:
        return pd.DataFrame()
    df = filter_rating_plays(pbp, wp_col=wp_col)
    rows: list[dict] = []
    for gid, grp in df.groupby("game_id", sort=False):
        home = grp["home_team"].iloc[0] if "home_team" in grp.columns else None
        away = grp["away_team"].iloc[0] if "away_team" in grp.columns else None
        if not home or not away:
            continue
        rows.append(
            {
                "game_id": str(gid),
                "home_team": str(home),
                "away_team": str(away),
                "home_plays": team_offensive_plays_in_game(grp, team=str(home)),
                "away_plays": team_offensive_plays_in_game(grp, team=str(away)),
            }
        )
    return pd.DataFrame(rows)
