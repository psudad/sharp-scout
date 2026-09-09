"""Phase 1 — Micro-level opportunity & usage baselines for player props."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from sharp_scout.config import get_settings
from sharp_scout.data.nflfastr import load_pbp
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)


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


def _weighted_per_game(
    frame: pd.DataFrame,
    id_col: str,
    sums: dict[str, str],
    *,
    max_season: int,
    decay: float,
) -> pd.DataFrame:
    """Recency-weighted per-game rates, indexed by player id.

    `sums` maps an output column to the source column summed per player-season. Each
    season is weighted `decay ** (max_season - season)` so an older season cannot carry
    the same weight as the most recent one, then totals are divided by weighted games.
    Also returns raw (unweighted) `games` and `recent_games` for eligibility checks.
    """
    agg: dict[str, tuple[str, str]] = {out: (src, "sum") for out, src in sums.items()}
    agg["games"] = ("game_id", "nunique")
    grouped = frame.groupby([id_col, "season"], dropna=True).agg(**agg).reset_index()
    grouped["season"] = grouped["season"].astype(int)
    grouped["weight"] = decay ** (max_season - grouped["season"])

    weighted = grouped.copy()
    for col in [*sums, "games"]:
        weighted[col] = weighted[col].astype(float) * weighted["weight"]
    totals = weighted.groupby(id_col)[[*sums, "games"]].sum()

    weighted_games = totals["games"].replace(0.0, np.nan)
    out = totals[[*sums]].div(weighted_games, axis=0).fillna(0.0)
    out["games"] = grouped.groupby(id_col)["games"].sum()
    out["recent_games"] = (
        grouped[grouped["season"] >= max_season - 1].groupby(id_col)["games"].sum()
    )
    out["recent_games"] = out["recent_games"].fillna(0)
    return out


def _player_directory() -> dict[str, dict[str, Any]]:
    """gsis_id → display name / position / current team from the nflverse directory."""
    from sharp_scout.data.nflfastr import load_players

    players = load_players()
    if players.empty:
        return {}
    directory: dict[str, dict[str, Any]] = {}
    for row in players.itertuples(index=False):
        pid = str(getattr(row, "gsis_id", "") or "")
        name = str(getattr(row, "display_name", "") or "").strip()
        if not pid or not name:
            continue
        team = getattr(row, "latest_team", None)
        directory[pid] = {
            "name": name,
            "position": str(getattr(row, "position", "") or "").upper(),
            "team": str(team) if isinstance(team, str) and team.strip() else "",
        }
    return directory


def build_usage_profiles(
    pbp: pd.DataFrame | None = None,
    seasons: list[int] | None = None,
    min_games: int = 2,
) -> dict[str, PlayerUsage]:
    """Build opponent-agnostic usage baselines keyed by normalized full player name.

    Play-by-play only carries abbreviated names ("J.Smith-Njigba") and no positions, so
    the nflverse player directory supplies the display name that sportsbooks use, the
    real position, and the team the player is on *now* — otherwise a player who changed
    teams gets stranded on an old roster and never matches his current game.
    """
    settings = get_settings()
    seasons = seasons or settings.seasons
    if pbp is None:
        pbp = load_pbp(seasons)

    if pbp.empty:
        logger.warning("No play-by-play available — cannot build prop usage profiles")
        return {}

    df = pbp
    if "season" in df.columns:
        df = df[df["season"].isin(seasons)]
    if df.empty or "game_id" not in df.columns:
        logger.warning("No usable play-by-play rows for seasons %s", seasons)
        return {}

    directory = _player_directory()
    if not directory:
        logger.warning("nflverse player directory unavailable — cannot build prop usage")
        return {}

    max_season = int(df["season"].max())
    decay = float(settings.prop_season_decay)

    def _flag(col: str) -> pd.Series:
        if col in df.columns:
            return df[col].fillna(0).astype(float)
        return pd.Series(0.0, index=df.index)

    is_pass = _flag("pass") > 0
    is_sack = _flag("sack") > 0
    is_rush = df["is_rush_attempt"] if "is_rush_attempt" in df.columns else (_flag("rush") > 0)

    profiles: dict[str, PlayerUsage] = {}

    def _profile_for(pid: str) -> PlayerUsage | None:
        info = directory.get(pid)
        if info is None:
            return None
        key = _player_key(info["name"])
        existing = profiles.get(key)
        if existing is not None:
            return existing
        created = PlayerUsage(
            player_id=pid,
            player_name=info["name"],
            team=info["team"],
            position=info["position"],
        )
        profiles[key] = created
        return created

    # ---- Receiving -------------------------------------------------------------
    if "receiver_player_id" in df.columns:
        recv = df[df["receiver_player_id"].notna() & is_pass].copy()
        if not recv.empty:
            recv["targets"] = 1.0
            recv["receptions"] = _flag("complete_pass").reindex(recv.index).fillna(0.0)
            recv["rec_yards"] = (
                recv["receiving_yards"].fillna(0.0)
                if "receiving_yards" in recv.columns
                else recv.get("yards_gained", pd.Series(0.0, index=recv.index)).fillna(0.0)
            )
            recv["rec_tds"] = _flag("pass_touchdown").reindex(recv.index).fillna(0.0)
            recv["air"] = (
                recv["air_yards"].fillna(0.0)
                if "air_yards" in recv.columns
                else pd.Series(0.0, index=recv.index)
            )
            recv["rz_targets"] = (
                (recv["yardline_100"] <= 20).astype(float)
                if "yardline_100" in recv.columns
                else 0.0
            )
            rates = _weighted_per_game(
                recv,
                "receiver_player_id",
                {
                    "targets": "targets",
                    "receptions": "receptions",
                    "rec_yards": "rec_yards",
                    "rec_tds": "rec_tds",
                    "air": "air",
                    "rz_targets": "rz_targets",
                },
                max_season=max_season,
                decay=decay,
            )
            for pid, row in rates.iterrows():
                if row["games"] < min_games or row["recent_games"] < 1:
                    continue
                u = _profile_for(str(pid))
                if u is None:
                    continue
                u.exp_targets = float(row["targets"])
                u.exp_receptions = float(row["receptions"])
                u.exp_rec_yards = float(row["rec_yards"])
                u.exp_rec_tds = float(row["rec_tds"])
                u.catch_rate = (
                    float(row["receptions"] / row["targets"]) if row["targets"] else 0.65
                )
                u.ypt = float(row["rec_yards"] / row["targets"]) if row["targets"] else 7.0
                u.games = int(row["games"])
                # Routes are not in the free feed; back them out of a league-average TPRR.
                routes = max(u.exp_targets / 0.22, u.exp_targets)
                u.tprr = u.exp_targets / routes if routes else 0.22
                u.yprr = u.exp_rec_yards / routes if routes else 1.5
                u.meta = {**(u.meta or {}), "air_yards_per_game": float(row["air"])}

    # ---- Rushing ---------------------------------------------------------------
    if "rusher_player_id" in df.columns:
        rush = df[df["rusher_player_id"].notna() & is_rush].copy()
        if not rush.empty:
            rush["attempts"] = 1.0
            rush["rush_yards"] = (
                rush["rushing_yards"].fillna(0.0)
                if "rushing_yards" in rush.columns
                else rush.get("yards_gained", pd.Series(0.0, index=rush.index)).fillna(0.0)
            )
            rush["rush_tds"] = _flag("rush_touchdown").reindex(rush.index).fillna(0.0)
            rates = _weighted_per_game(
                rush,
                "rusher_player_id",
                {
                    "attempts": "attempts",
                    "rush_yards": "rush_yards",
                    "rush_tds": "rush_tds",
                },
                max_season=max_season,
                decay=decay,
            )
            for pid, row in rates.iterrows():
                if row["games"] < min_games or row["recent_games"] < 1:
                    continue
                u = _profile_for(str(pid))
                if u is None:
                    continue
                u.exp_rush_att = float(row["attempts"])
                u.exp_rush_yards = float(row["rush_yards"])
                u.exp_rush_tds = float(row["rush_tds"])
                u.ypc_rush = (
                    float(row["rush_yards"] / row["attempts"]) if row["attempts"] else 4.0
                )
                u.games = max(u.games, int(row["games"]))

    # ---- Passing ---------------------------------------------------------------
    if "passer_player_id" in df.columns:
        pas = df[df["passer_player_id"].notna() & is_pass & ~is_sack].copy()
        if not pas.empty:
            pas["attempts"] = 1.0
            pas["pass_yards"] = (
                pas["passing_yards"].fillna(0.0)
                if "passing_yards" in pas.columns
                else pas.get("yards_gained", pd.Series(0.0, index=pas.index)).fillna(0.0)
            )
            pas["pass_tds"] = _flag("pass_touchdown").reindex(pas.index).fillna(0.0)
            rates = _weighted_per_game(
                pas,
                "passer_player_id",
                {
                    "attempts": "attempts",
                    "pass_yards": "pass_yards",
                    "pass_tds": "pass_tds",
                },
                max_season=max_season,
                decay=decay,
            )
            cpoe = (
                pas.groupby("passer_player_id")["cpoe"].mean()
                if "cpoe" in pas.columns
                else pd.Series(dtype=float)
            )
            for pid, row in rates.iterrows():
                if row["games"] < min_games or row["recent_games"] < 1:
                    continue
                u = _profile_for(str(pid))
                if u is None:
                    continue
                u.exp_pass_att = float(row["attempts"])
                u.exp_pass_yards = float(row["pass_yards"])
                u.exp_pass_tds = float(row["pass_tds"])
                u.cpoe = float(cpoe.get(pid, 0.0) or 0.0)
                u.games = max(u.games, int(row["games"]))

    # ---- Team shares -----------------------------------------------------------
    team_targets: dict[str, float] = {}
    team_rush_att: dict[str, float] = {}
    for u in profiles.values():
        if not u.team:
            continue
        team_targets[u.team] = team_targets.get(u.team, 0.0) + u.exp_targets
        team_rush_att[u.team] = team_rush_att.get(u.team, 0.0) + u.exp_rush_att
    for u in profiles.values():
        tt = team_targets.get(u.team, 0.0)
        ra = team_rush_att.get(u.team, 0.0)
        u.target_share = u.exp_targets / tt if tt else 0.0
        u.rush_share = u.exp_rush_att / ra if ra else 0.0
        u.route_participation = float(np.clip(u.exp_targets / 6.0, 0.0, 1.0))

    # Drop players with no usable volume in any market — a profile of all zeros would
    # otherwise simulate as "near-certain under" on every line.
    profiles = {k: u for k, u in profiles.items() if _has_usable_volume(u)}

    logger.info("Built usage profiles for %d players", len(profiles))
    return profiles


def _has_usable_volume(u: PlayerUsage) -> bool:
    return (
        u.exp_targets > 0
        or u.exp_rush_att > 0
        or u.exp_pass_att > 0
    )


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
    """Match a sportsbook player name to a usage profile.

    Only exact and unambiguous first-initial+surname matches count. A bare surname
    substring match used to silently return whichever player happened to be first in the
    dict, attributing one player's projection to another.
    """
    key = _player_key(name)
    if key in profiles:
        return profiles[key]

    parts = key.split()
    if len(parts) < 2:
        return None
    surname = parts[-1]
    initial = parts[0][0]

    candidates = [
        p
        for k, p in profiles.items()
        if k.split()[-1:] == [surname] and k.startswith(initial)
    ]
    if len(candidates) == 1:
        return candidates[0]
    # Ambiguous (or no) surname match — better to skip than to guess wrong.
    return None