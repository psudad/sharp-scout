"""Team pace / scoring rates from nflverse play-by-play."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

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
    elif "play_type" in drive_plays.columns:
        # nflverse marks attempts on the field_goal row only
        fgs = (drive_plays["play_type"] == "field_goal").sum()
        pts += 3.0 * fgs
    if "safety" in drive_plays.columns:
        saf = drive_plays["safety"].fillna(0).astype(float).sum()
        pts += 2.0 * saf
    return float(pts)


def _totals_pbp_plays(pbp: pd.DataFrame) -> pd.DataFrame:
    """Scoring-relevant plays for totals (includes FGs; no EPA filter)."""
    if pbp.empty:
        return pbp
    df = pbp.copy()
    if "play_type" in df.columns:
        scoring_types = ("pass", "run", "qb_kneel", "qb_spike", "field_goal")
        df = df[df["play_type"].isin(scoring_types) | df["play_type"].isna()]
    return df[df["posteam"].notna() & df["fixed_drive"].notna()].copy()


def build_team_drive_rates(pbp: pd.DataFrame) -> dict[str, TeamDriveRates]:
    """Team scoring pace from recent drives."""
    if pbp.empty or "fixed_drive" not in pbp.columns:
        return _league_defaults_only()

    df = _totals_pbp_plays(pbp)
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
                "pts_w": pts * w,
                "drive_w": w,
                "drive_count": 1.0,
                "plays_w": n_plays * w,
                "rz_td_w": rz_td * w,
                "rz_w": w if not rz.empty else 0.0,
            }
        )

    if not drive_rows:
        return _league_defaults_only()

    ddf = pd.DataFrame(drive_rows)
    # Drives per game: unweighted count (recency weights apply to rate stats, not volume)
    game_drives = ddf.groupby(["team", "game_id"], as_index=False)["drive_count"].sum()
    dpg = game_drives.groupby("team")["drive_count"].mean()

    agg = ddf.groupby("team", as_index=False).sum()
    out: dict[str, TeamDriveRates] = {}
    for _, r in agg.iterrows():
        team = str(r["team"])
        drive_w = float(r["drive_w"]) or 1.0
        plays_w = float(r["plays_w"]) or drive_w * LEAGUE_DEFAULTS["plays_per_drive"]
        rz_w = float(r["rz_w"]) or drive_w * 0.35
        dpg_val = float(dpg.get(team, LEAGUE_DEFAULTS["drives_per_game"]))
        ppd = float(r["pts_w"]) / drive_w
        out[team] = TeamDriveRates(
            team=team,
            drives_per_game=float(np.clip(dpg_val, 9.0, 14.0)),
            pts_per_drive=float(np.clip(ppd, 1.45, 2.85)),
            rz_td_rate=float(np.clip(float(r["rz_td_w"]) / max(rz_w, 1.0), 0.35, 0.75)),
            plays_per_drive=float(np.clip(plays_w / drive_w, 4.0, 8.0)),
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
