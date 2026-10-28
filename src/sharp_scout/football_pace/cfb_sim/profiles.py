"""Team profiles from 2026 drives only (opponent-adjusted at sim time)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LEAGUE = {
    "td": 0.22,
    "fg": 0.11,
    "miss_fg": 0.03,
    "punt": 0.38,
    "int": 0.05,
    "fumble": 0.04,
    "downs": 0.09,
    "other": 0.08,
}
OUTCOMES = ("td", "fg", "miss_fg", "punt", "int", "fumble", "downs", "other")
HFA_POINTS = 2.75
MIN_DRIVES = 12


@dataclass
class TeamProfile:
    team: str
    drives_per_game: float = 11.5
    plays_per_drive: float = 6.0
    sec_per_play: float = 5.5
    outcome_rates: dict[str, float] = field(default_factory=lambda: dict(LEAGUE))
    int_rate: float = 0.045
    fumble_rate: float = 0.035
    pass_play_share: float = 0.55
    def_td_allow: float = 0.22
    def_to_forced: float = 0.09
    havoc_rate: float = 0.08
    punt_net_yards: float = 38.0
    turnover_margin: float = 0.0
    n_off_drives: int = 0
    def_epa_allowed: float | None = None
    def_success_allowed: float | None = None
    def_epa_rank: int | None = None


def _rate(count: int, n: int, prior: float, pseudo: int = 20) -> float:
    return (count + pseudo * prior) / (n + pseudo)


def build_profiles(drives: pd.DataFrame, play_df: pd.DataFrame | None = None) -> dict[str, TeamProfile]:
    profiles: dict[str, TeamProfile] = {}
    if drives.empty:
        return profiles

    off = drives[drives["offense"].astype(str).str.len() > 0]
    dpg_by_team = off.groupby(["offense", "game_id"]).size().groupby("offense").mean()
    league_dpg = float(dpg_by_team.mean()) if len(dpg_by_team) else 11.5
    league_ppd = off["plays"].mean() if len(off) else 6.0
    league_spp = (off["sec"] / off["plays"].clip(lower=1)).mean() if len(off) else 5.5

    def_td = off[off["result"] == "td"].groupby("defense").size()
    def_drv_count = off.groupby("defense").size()

    teams = set(off["offense"].astype(str)) | set(off["defense"].astype(str))
    for team in teams:
        team = str(team)
        if not team or team in ("nan", "None", ""):
            continue
        sub = off[off["offense"] == team]
        n_drv = len(sub)
        if n_drv < MIN_DRIVES:
            continue
        n = max(n_drv, 1)
        rates = {k: _rate(int((sub["result"] == k).sum()), n, LEAGUE[k]) for k in OUTCOMES}
        s = sum(rates.values())
        rates = {k: v / s for k, v in rates.items()}

        dpg = float(dpg_by_team.get(team, league_dpg))
        ppd = float(sub["plays"].mean()) if len(sub) else league_ppd
        spp = float((sub["sec"] / sub["plays"].clip(lower=1)).mean()) if len(sub) else league_spp

        def_n = int(def_drv_count.get(team, 0))
        td_allow = _rate(int(def_td.get(team, 0)), max(def_n, 1), LEAGUE["td"])
        to_forced = _rate(
            int((off[(off["defense"] == team) & off["result"].isin(["int", "fumble"])].shape[0])),
            max(def_n, 1),
            LEAGUE["int"] + LEAGUE["fumble"],
        )

        int_rate = _rate(int((sub["result"] == "int").sum()), n, LEAGUE["int"])
        fum_rate = _rate(int((sub["result"] == "fumble").sum()), n, LEAGUE["fumble"])
        tm = (int_rate + fum_rate) - to_forced
        tm *= 0.35  # regress turnover margin toward average

        punt_yards = 38.0
        punts = sub[sub["result"] == "punt"]
        if len(punts) and "drive_yards" in punts.columns:
            y = pd.to_numeric(punts["drive_yards"], errors="coerce").dropna()
            if len(y):
                punt_yards = float(y.mean())

        pass_share = 0.55
        if play_df is not None and not play_df.empty and "posteam" in play_df.columns:
            tp = play_df[play_df["posteam"] == team]
            if len(tp) > 50:
                drop = tp["is_dropback"].astype(bool).sum() if "is_dropback" in tp.columns else 0
                rush = tp["is_rush"].astype(bool).sum() if "is_rush" in tp.columns else 0
                scr = drop + rush
                if scr > 0:
                    pass_share = drop / scr

        havoc = 0.08
        if play_df is not None and "sack" in play_df.columns:
            def_col = "defteam" if "defteam" in play_df.columns else "def_pos_team"
            dp = play_df[play_df[def_col] == team] if def_col in play_df.columns else pd.DataFrame()
            if len(dp) > 100:
                havoc = float(pd.to_numeric(dp.get("sack"), errors="coerce").fillna(0).astype(bool).mean())

        profiles[team] = TeamProfile(
            team=team,
            drives_per_game=max(8.0, min(16.0, dpg)),
            plays_per_drive=max(3.5, min(10.0, ppd)),
            sec_per_play=max(4.0, min(8.0, spp)),
            outcome_rates=rates,
            int_rate=max(0.01, min(0.12, int_rate - tm / 2)),
            fumble_rate=max(0.01, min(0.10, fum_rate - tm / 2)),
            pass_play_share=pass_share,
            def_td_allow=td_allow,
            def_to_forced=to_forced,
            havoc_rate=havoc,
            punt_net_yards=punt_yards,
            turnover_margin=tm,
            n_off_drives=n_drv,
        )

    _attach_def_epa_ranks(profiles, play_df)
    return profiles


def _attach_def_epa_ranks(profiles: dict[str, TeamProfile], play_df: pd.DataFrame | None) -> None:
    if play_df is None or play_df.empty or "epa" not in play_df.columns:
        return
    def_col = "defteam" if "defteam" in play_df.columns else None
    if not def_col:
        return
    epa = pd.to_numeric(play_df["epa"], errors="coerce")
    df = play_df.assign(_epa=epa)
    df = df[df["_epa"].notna() & df[def_col].astype(str).str.len().gt(0)]
    if df.empty:
        return
    grp = df.groupby(def_col)["_epa"].mean()
    succ = None
    if "success" in df.columns:
        succ = df.groupby(def_col)["success"].mean()
    ranked = grp.sort_values()
    for i, t in enumerate(ranked.index.astype(str)):
        if t not in profiles:
            continue
        profiles[t].def_epa_allowed = float(ranked.iloc[i])
        profiles[t].def_epa_rank = i + 1
        if succ is not None and t in succ.index.astype(str):
            profiles[t].def_success_allowed = float(succ.loc[t])


def adjusted_outcome_rates(off: TeamProfile, defn: TeamProfile) -> dict[str, float]:
    out: dict[str, float] = {}
    for k in OUTCOMES:
        o = off.outcome_rates.get(k, LEAGUE[k])
        if k == "td":
            d = defn.def_td_allow
            out[k] = (o * d) / LEAGUE["td"]
        elif k in ("int", "fumble"):
            d = defn.def_to_forced / 2.0
            out[k] = (o * (d / (LEAGUE[k] or 0.05))) * (1.0 + defn.havoc_rate)
        else:
            out[k] = o
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


def fallback_profile(team: str) -> TeamProfile:
    return TeamProfile(team=team, outcome_rates=dict(LEAGUE), n_off_drives=0)


def get_profile(profiles: dict[str, TeamProfile], team: str) -> TeamProfile:
    return profiles.get(team) or fallback_profile(team)
