"""Phase 1 — Micro-level opportunity & usage baselines for player props."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from sharp_scout.config import DATA_DIR, get_settings
from sharp_scout.data.nflfastr import CACHE_DIR, _download, load_pbp
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

PLAYER_STATS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/player_stats/"
    "player_stats.parquet"
)
SNAP_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/"
    "snap_counts.parquet"
)


@dataclass
class PlayerUsage:
    player_id: str
    player_name: str
    team: str
    position: str
    # Volume
    route_participation: float = 0.0  # approx: routes / team dropbacks
    target_share: float = 0.0
    air_yards_share: float = 0.0
    snap_pct: float = 0.0
    rz_touch_share: float = 0.0
    rush_share: float = 0.0
    # Efficiency
    tprr: float = 0.0  # targets per route run
    yprr: float = 0.0
    cpoe: float = 0.0
    # Rate baselines (per-game expectations before matchup/script)
    exp_targets: float = 0.0
    exp_receptions: float = 0.0
    exp_rec_yards: float = 0.0
    exp_rush_att: float = 0.0
    exp_rush_yards: float = 0.0
    exp_pass_att: float = 0.0
    exp_pass_yards: float = 0.0
    exp_pass_tds: float = 0.0
    exp_rec_tds: float = 0.0
    exp_rush_tds: float = 0.0
    catch_rate: float = 0.0
    ypt: float = 0.0  # yards per target
    ypc_rush: float = 0.0
    games: int = 0
    inactive: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


def _load_parquet_cached(name: str, url: str) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / name
    if not path.exists():
        logger.info("Downloading %s", name)
        if not _download(url, path):
            return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed reading %s: %s", name, exc)
        return pd.DataFrame()


def build_usage_profiles(
    pbp: pd.DataFrame | None = None,
    seasons: list[int] | None = None,
    min_games: int = 2,
) -> dict[str, PlayerUsage]:
    """Build opponent-agnostic usage baselines keyed by normalized player name."""
    settings = get_settings()
    seasons = seasons or settings.seasons
    if pbp is None:
        pbp = load_pbp(seasons)

    snaps = _load_parquet_cached("snap_counts.parquet", SNAP_URL)
    if not snaps.empty and "season" in snaps.columns:
        snaps = snaps[snaps["season"].isin(seasons)]

    if pbp.empty:
        logger.warning("No PBP for usage profiles — returning demo stubs")
        return _demo_usage()

    # Recency weight by week within latest seasons
    df = pbp.copy()
    if "season" in df.columns:
        df = df[df["season"].isin(seasons)]

    dropbacks = df[df.get("is_dropback", False) == True] if "is_dropback" in df.columns else df
    team_dropbacks = (
        dropbacks.groupby(["season", "week", "posteam"]).size().rename("team_db").reset_index()
        if not dropbacks.empty
        else pd.DataFrame()
    )

    # Receiving opportunities
    recv = df[df["receiver_player_name"].notna()].copy() if "receiver_player_name" in df.columns else pd.DataFrame()
    # Fallback column names in nflverse
    if recv.empty and "receiver_player_id" in df.columns:
        recv = df[df["receiver_player_id"].notna()].copy()

    profiles: dict[str, PlayerUsage] = {}

    if not recv.empty:
        name_col = "receiver_player_name" if "receiver_player_name" in recv.columns else None
        if name_col:
            recv["player_name"] = recv[name_col].astype(str)
            recv["team"] = recv["posteam"].map(lambda x: normalize_team(str(x)))
            # Routes approx: each target counts; also count as route if complete/incomplete pass to them
            # Better: use player on pass plays — approximate routes ~= targets / typical TPRR later
            g = recv.groupby(["player_name", "team"], dropna=False)
            for (pname, team), sub in g:
                games = sub.groupby(["season", "week"]).ngroups if {"season", "week"}.issubset(sub.columns) else max(len(sub) // 8, 1)
                if games < min_games:
                    continue
                targets = len(sub)
                air = float(sub["air_yards"].sum()) if "air_yards" in sub.columns else 0.0
                catches = float(sub["complete_pass"].sum()) if "complete_pass" in sub.columns else float(
                    (sub["yards_gained"] > 0).sum()
                ) if "yards_gained" in sub.columns else targets * 0.65
                rec_yards = float(sub["yards_gained"].sum()) if "yards_gained" in sub.columns else 0.0
                # Red zone targets
                rz = sub
                if "yardline_100" in sub.columns:
                    rz = sub[sub["yardline_100"] <= 20]
                rz_tgts = len(rz)
                tds = float(sub["touchdown"].sum()) if "touchdown" in sub.columns else 0.0

                # Team totals for shares
                team_tgts = len(recv[recv["team"] == team]) if "team" in recv.columns else targets
                team_air = float(recv.loc[recv["team"] == team, "air_yards"].sum()) if "air_yards" in recv.columns else air
                team_rz = len(recv[(recv["team"] == team) & (recv.get("yardline_100", pd.Series(99)) <= 20)]) if "yardline_100" in recv.columns else rz_tgts

                # Team dropbacks for route participation proxy
                team_db = 0
                if not team_dropbacks.empty:
                    team_db = int(
                        team_dropbacks.loc[team_dropbacks["posteam"].map(lambda x: normalize_team(str(x))) == team, "team_db"].sum()
                    )
                # Approximate routes as targets / 0.22 TPRR league avg when snap data missing
                routes = max(targets / 0.22, targets)
                route_part = (routes / team_db) if team_db else min(targets / max(games * 35, 1), 1.0)

                catch_rate = catches / targets if targets else 0.65
                ypt = rec_yards / targets if targets else 7.0
                key = _player_key(pname)
                profiles[key] = PlayerUsage(
                    player_id=key,
                    player_name=pname,
                    team=team,
                    position="WR",
                    route_participation=float(np.clip(route_part, 0, 1)),
                    target_share=targets / team_tgts if team_tgts else 0.0,
                    air_yards_share=air / team_air if team_air else 0.0,
                    rz_touch_share=rz_tgts / team_rz if team_rz else 0.0,
                    tprr=targets / routes if routes else 0.22,
                    yprr=rec_yards / routes if routes else 1.5,
                    exp_targets=targets / games,
                    exp_receptions=catches / games,
                    exp_rec_yards=rec_yards / games,
                    exp_rec_tds=tds / games,
                    catch_rate=catch_rate,
                    ypt=ypt,
                    games=games,
                )

    # Rushing
    rush = df[df.get("is_rush", False) == True].copy() if "is_rush" in df.columns else pd.DataFrame()
    if rush.empty and "rusher_player_name" in df.columns:
        rush = df[df["rusher_player_name"].notna()].copy()
    if not rush.empty and "rusher_player_name" in rush.columns:
        rush["player_name"] = rush["rusher_player_name"].astype(str)
        rush["team"] = rush["posteam"].map(lambda x: normalize_team(str(x)))
        for (pname, team), sub in rush.groupby(["player_name", "team"]):
            games = sub.groupby(["season", "week"]).ngroups if {"season", "week"}.issubset(sub.columns) else max(len(sub) // 10, 1)
            if games < min_games:
                continue
            att = len(sub)
            yds = float(sub["yards_gained"].sum()) if "yards_gained" in sub.columns else 0.0
            tds = float(sub["touchdown"].sum()) if "touchdown" in sub.columns else 0.0
            team_att = len(rush[rush["team"] == team])
            key = _player_key(pname)
            if key in profiles:
                profiles[key].rush_share = att / team_att if team_att else 0.0
                profiles[key].exp_rush_att = att / games
                profiles[key].exp_rush_yards = yds / games
                profiles[key].exp_rush_tds = tds / games
                profiles[key].ypc_rush = yds / att if att else 4.0
                if profiles[key].position == "WR" and att / games > 3:
                    profiles[key].position = "RB"
            else:
                profiles[key] = PlayerUsage(
                    player_id=key,
                    player_name=pname,
                    team=team,
                    position="RB",
                    rush_share=att / team_att if team_att else 0.0,
                    exp_rush_att=att / games,
                    exp_rush_yards=yds / games,
                    exp_rush_tds=tds / games,
                    ypc_rush=yds / att if att else 4.0,
                    games=games,
                )

    # Passing (QB)
    if "passer_player_name" in df.columns:
        pas = df[df["passer_player_name"].notna() & df.get("is_dropback", True)].copy()
        pas["player_name"] = pas["passer_player_name"].astype(str)
        pas["team"] = pas["posteam"].map(lambda x: normalize_team(str(x)))
        for (pname, team), sub in pas.groupby(["player_name", "team"]):
            games = sub.groupby(["season", "week"]).ngroups if {"season", "week"}.issubset(sub.columns) else max(len(sub) // 30, 1)
            if games < min_games:
                continue
            att = len(sub)
            yds = float(sub["yards_gained"].sum()) if "yards_gained" in sub.columns else 0.0
            tds = float(sub["touchdown"].sum()) if "touchdown" in sub.columns else 0.0
            cpoe = float(sub["cpoe"].mean()) if "cpoe" in sub.columns else 0.0
            key = _player_key(pname)
            if key in profiles and profiles[key].exp_targets > 2:
                continue  # skill player who also has passer rows
            profiles[key] = PlayerUsage(
                player_id=key,
                player_name=pname,
                team=team,
                position="QB",
                exp_pass_att=att / games,
                exp_pass_yards=yds / games,
                exp_pass_tds=tds / games,
                cpoe=cpoe,
                games=games,
            )

    # Snap % overlay
    if not snaps.empty:
        name_col = "player" if "player" in snaps.columns else ("player_name" if "player_name" in snaps.columns else None)
        pct_col = "offense_pct" if "offense_pct" in snaps.columns else None
        if name_col and pct_col:
            for _, row in snaps.groupby(name_col)[pct_col].mean().items():
                pass
            avg = snaps.groupby(name_col)[pct_col].mean()
            for pname, pct in avg.items():
                key = _player_key(str(pname))
                if key in profiles:
                    # offense_pct often 0-100
                    profiles[key].snap_pct = float(pct) / 100.0 if pct > 1.5 else float(pct)

    logger.info("Built usage profiles for %d players", len(profiles))
    return profiles if profiles else _demo_usage()


def apply_game_script(
    usage: PlayerUsage,
    *,
    team_spread: float,
    team_total: float,
    is_home: bool,
) -> PlayerUsage:
    """Adjust volume for game script: trailing underdogs → more pass volume."""
    # team_spread: points on this player's team (negative = favored)
    pass_mult = 1.0
    rush_mult = 1.0
    if team_spread >= 3.5:  # underdog
        pass_mult += min(0.12, 0.02 * (team_spread / 3.5))
        rush_mult -= min(0.08, 0.015 * (team_spread / 3.5))
    elif team_spread <= -3.5:  # favorite
        pass_mult -= min(0.08, 0.015 * (abs(team_spread) / 3.5))
        rush_mult += min(0.10, 0.02 * (abs(team_spread) / 3.5))

    # High totals lift all volume slightly
    if team_total >= 48:
        pass_mult += 0.04
        rush_mult += 0.02
    elif team_total <= 40:
        pass_mult -= 0.03
        rush_mult -= 0.02

    u = PlayerUsage(**{**usage.__dict__})
    u.exp_targets *= pass_mult
    u.exp_receptions *= pass_mult
    u.exp_rec_yards *= pass_mult
    u.exp_pass_att *= pass_mult
    u.exp_pass_yards *= pass_mult
    u.exp_pass_tds *= pass_mult
    u.exp_rec_tds *= pass_mult
    u.exp_rush_att *= rush_mult
    u.exp_rush_yards *= rush_mult
    u.exp_rush_tds *= rush_mult
    u.meta = {**(usage.meta or {}), "pass_mult": pass_mult, "rush_mult": rush_mult}
    return u


def apply_matchup(
    usage: PlayerUsage,
    *,
    opp_pass_epa_allowed: float = 0.0,
    slot_vs_perimeter: str = "perimeter",
) -> PlayerUsage:
    """Light defensive matchup tilt using opponent EPA allowed to pass."""
    # Positive opp EPA allowed → softer pass D → boost receiving/pass
    tilt = 1.0 + float(np.clip(opp_pass_epa_allowed * 0.8, -0.12, 0.12))
    u = PlayerUsage(**{**usage.__dict__})
    if usage.position in ("WR", "TE", "RB"):
        u.exp_targets *= tilt
        u.exp_receptions *= tilt
        u.exp_rec_yards *= tilt * (1.02 if slot_vs_perimeter == "slot" else 1.0)
    if usage.position == "QB":
        u.exp_pass_yards *= tilt
        u.exp_pass_tds *= tilt
    u.meta = {**(u.meta or {}), "matchup_tilt": tilt}
    return u


def reallocate_targets(
    profiles: dict[str, PlayerUsage],
    team: str,
    inactive_names: list[str],
    redistribute_frac: float = 0.40,
) -> dict[str, PlayerUsage]:
    """Phase 4 usage re-allocation when a starter is inactive."""
    team = normalize_team(team)
    inactive_keys = {_player_key(n) for n in inactive_names}
    out = {k: PlayerUsage(**{**v.__dict__}) for k, v in profiles.items()}

    freed_targets = 0.0
    freed_rz = 0.0
    for k in list(out):
        p = out[k]
        if p.team != team:
            continue
        if k in inactive_keys or p.player_name in inactive_names:
            freed_targets += p.exp_targets * redistribute_frac
            freed_rz += p.exp_rec_tds * redistribute_frac
            p.inactive = True
            p.exp_targets *= 1 - redistribute_frac
            p.exp_receptions *= 1 - redistribute_frac
            p.exp_rec_yards *= 1 - redistribute_frac
            p.exp_rec_tds *= 1 - redistribute_frac
            p.meta = {**(p.meta or {}), "inactive_haircut": redistribute_frac}

    # Distribute to remaining pass-catchers on team by existing target share
    actives = [
        p
        for p in out.values()
        if p.team == team and not p.inactive and p.position in ("WR", "TE", "RB") and p.exp_targets > 0.5
    ]
    weights = np.array([p.exp_targets for p in actives], dtype=float)
    if weights.sum() <= 0 or freed_targets <= 0:
        return out
    weights = weights / weights.sum()
    for p, w in zip(actives, weights):
        p.exp_targets += freed_targets * w
        p.exp_receptions = p.exp_targets * max(p.catch_rate, 0.55)
        p.exp_rec_yards = p.exp_targets * max(p.ypt, 6.0)
        p.exp_rec_tds += freed_rz * w
        p.meta = {**(p.meta or {}), "reallocated": True}
    return out


def _player_key(name: str) -> str:
    return " ".join(str(name).strip().lower().replace(".", "").split())


def _demo_usage() -> dict[str, PlayerUsage]:
    return {
        "josh allen": PlayerUsage(
            "josh allen", "Josh Allen", "BUF", "QB",
            exp_pass_att=34, exp_pass_yards=265, exp_pass_tds=2.0, games=10, snap_pct=1.0,
        ),
        "patrick mahomes": PlayerUsage(
            "patrick mahomes", "Patrick Mahomes", "KC", "QB",
            exp_pass_att=35, exp_pass_yards=275, exp_pass_tds=2.1, games=10, snap_pct=1.0,
        ),
        "stephon diggs": PlayerUsage(
            "stephon diggs", "Stefon Diggs", "BUF", "WR",
            route_participation=0.92, target_share=0.28, air_yards_share=0.32, snap_pct=0.88,
            tprr=0.25, yprr=2.1, exp_targets=9.5, exp_receptions=6.2, exp_rec_yards=78,
            exp_rec_tds=0.55, catch_rate=0.65, ypt=8.2, games=10,
        ),
        "travis kelce": PlayerUsage(
            "travis kelce", "Travis Kelce", "KC", "TE",
            route_participation=0.85, target_share=0.24, snap_pct=0.82,
            tprr=0.24, yprr=2.0, exp_targets=8.5, exp_receptions=6.0, exp_rec_yards=72,
            exp_rec_tds=0.5, catch_rate=0.70, ypt=8.5, games=10,
        ),
        "james cook": PlayerUsage(
            "james cook", "James Cook", "BUF", "RB",
            rush_share=0.55, snap_pct=0.65, exp_rush_att=16, exp_rush_yards=75,
            exp_rush_tds=0.6, exp_targets=3.0, exp_receptions=2.4, exp_rec_yards=20,
            ypc_rush=4.7, catch_rate=0.8, games=10,
        ),
    }


def find_player(profiles: dict[str, PlayerUsage], name: str) -> PlayerUsage | None:
    key = _player_key(name)
    if key in profiles:
        return profiles[key]
    # Fuzzy: last name match
    last = key.split()[-1] if key else ""
    for k, p in profiles.items():
        if last and last in k:
            return p
    return None