"""Team pace / scoring rates from nflverse play-by-play."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sharp_scout.data.nflfastr import nfl_rating_plays
from sharp_scout.phase1.ratings import _recency_weights
from sharp_scout.utils.odds import normalize_team

LEAGUE_DEFAULTS = {
    "drives_per_game": 11.2,
    "pts_per_drive": 1.95,
    "rz_td_rate": 0.55,
    "plays_per_drive": 5.8,
}


@dataclass
class TeamDriveRates:
    team: str
    drives_per_game: float
    pts_per_drive: float
    rz_td_rate: float
    plays_per_drive: float


def _drive_points(drive_plays: pd.DataFrame) -> float:
    pts = 0.0
    if "touchdown" in drive_plays.columns:
        tds = drive_plays["touchdown"].fillna(0).astype(float).sum()
        pts += 6.0 * tds
    if "field_goal_result" in drive_plays.columns:
        fgs = (drive_plays["field_goal_result"] == "made").sum()
        pts += 3.0 * fgs
    if "safety" in drive_plays.columns:
        saf = drive_plays["safety"].fillna(0).astype(float).sum()
        pts += 2.0 * saf
    return float(pts)


def build_team_drive_rates(pbp: pd.DataFrame) -> dict[str, TeamDriveRates]:
    """Team scoring pace from recent drives."""
    if pbp.empty or "fixed_drive" not in pbp.columns:
        return _league_defaults_only()

    df = nfl_rating_plays(pbp)
    df = df[df["posteam"].notna() & df["fixed_drive"].notna()].copy()
    if df.empty:
        return _league_defaults_only()

    weights = _recency_weights(df, get_settings_half_life())
    df["_w"] = weights

    drive_rows: list[dict] = []
    for (_, _, _, posteam, drive), grp in df.groupby(
        ["season", "week", "game_id", "posteam", "fixed_drive"], dropna=False
    ):
        team = normalize_team(str(posteam), "nfl") or str(posteam)
        w = float(grp["_w"].mean())
        pts = _drive_points(grp)
        n_plays = len(grp)
        rz = grp[pd.to_numeric(grp.get("yardline_100"), errors="coerce") <= 20]
        rz_td = float(rz["touchdown"].fillna(0).astype(float).max()) if not rz.empty else 0.0
        drive_rows.append(
            {
                "team": team,
                "game_id": grp["game_id"].iloc[0],
                "w": w,
                "pts": pts * w,
                "drives": w,
                "plays": n_plays * w,
                "rz_td": rz_td * w,
                "rz": w if not rz.empty else 0.0,
            }
        )

    if not drive_rows:
        return _league_defaults_only()

    ddf = pd.DataFrame(drive_rows)
    # Drives per game: average weighted drives per team-game
    game_drives = ddf.groupby(["team", "game_id"], as_index=False)["drives"].sum()
    dpg = game_drives.groupby("team")["drives"].mean()

    agg = ddf.groupby("team", as_index=False).sum()
    out: dict[str, TeamDriveRates] = {}
    for _, r in agg.iterrows():
        team = str(r["team"])
        drives = float(r["drives"]) or 1.0
        plays = float(r["plays"]) or drives * LEAGUE_DEFAULTS["plays_per_drive"]
        rz = float(r["rz"]) or drives * 0.35
        dpg_val = float(dpg.get(team, LEAGUE_DEFAULTS["drives_per_game"]))
        out[team] = TeamDriveRates(
            team=team,
            drives_per_game=float(np.clip(dpg_val, 8.5, 14.0)),
            pts_per_drive=float(np.clip(float(r["pts"]) / drives, 1.2, 2.8)),
            rz_td_rate=float(np.clip(float(r["rz_td"]) / max(rz, 1.0), 0.35, 0.75)),
            plays_per_drive=float(np.clip(plays / drives, 4.0, 8.0)),
        )
    return out


def get_settings_half_life() -> float:
    from sharp_scout.config import get_settings

    return float(get_settings().nfl_epa_half_life_weeks)


def _league_defaults_only() -> dict[str, TeamDriveRates]:
    teams = [
        "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
        "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
        "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
        "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
    ]
    return {
        t: TeamDriveRates(t, **LEAGUE_DEFAULTS)  # type: ignore[arg-type]
        for t in teams
    }


def team_rates(rates: dict[str, TeamDriveRates], team: str) -> TeamDriveRates:
    key = normalize_team(team, "nfl") or team
    if key in rates:
        return rates[key]
    return TeamDriveRates(
        key,
        LEAGUE_DEFAULTS["drives_per_game"],
        LEAGUE_DEFAULTS["pts_per_drive"],
        LEAGUE_DEFAULTS["rz_td_rate"],
        LEAGUE_DEFAULTS["plays_per_drive"],
    )
