"""Actual player stat lines per game, derived from play-by-play.

This is the settlement and grading source for player props. nflverse publishes a
`player_stats` release, but it currently stops at 2024, so results are recomputed from
the same play-by-play that builds the projections — which keeps the graded outcome
definitionally consistent with what the model was predicting.

Two consumers:

* `sharp_scout.ledger.tracker` — grades pending prop plays once a game is final.
* `sharp_scout.props.backfit` — grades reconstructed historical projections so a
  calibrator can be fit without waiting a full season for live results.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from sharp_scout.data.nflfastr import load_pbp, load_players
from sharp_scout.props.usage import _player_key

logger = logging.getLogger(__name__)

# Prop market → the stat that settles it.
RECEIVING_MARKETS = {
    "player_receptions": "receptions",
    "player_reception_yds": "receiving_yards",
    "player_reception_tds": "receiving_tds",
}
RUSHING_MARKETS = {
    "player_rush_attempts": "carries",
    "player_rush_yds": "rushing_yards",
    "player_rush_tds": "rushing_tds",
}
PASSING_MARKETS = {
    "player_pass_attempts": "attempts",
    "player_pass_yds": "passing_yards",
    "player_pass_tds": "passing_tds",
}
ANYTIME_TD_MARKET = "player_anytime_td"

SETTLEABLE_MARKETS = (
    set(RECEIVING_MARKETS) | set(RUSHING_MARKETS) | set(PASSING_MARKETS) | {ANYTIME_TD_MARKET}
)

_GAME_KEYS = ["season", "week", "game_id"]


def _flag(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return df[col].fillna(0).astype(float)
    return pd.Series(0.0, index=df.index)


def player_game_stats(pbp: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per player, per game stat totals.

    Returns one row per (season, week, game_id, player_id) with a column for every
    settleable stat. Players who only appear in one role still get zeros elsewhere, so
    an "anytime TD" no can be graded for a pure rusher or receiver.
    """
    if pbp is None:
        pbp = load_pbp()
    if pbp.empty:
        return pd.DataFrame()

    is_pass = _flag(pbp, "pass") > 0
    is_sack = _flag(pbp, "sack") > 0
    is_rush = (
        pbp["is_rush_attempt"] if "is_rush_attempt" in pbp.columns else (_flag(pbp, "rush") > 0)
    )

    frames: list[pd.DataFrame] = []

    if "receiver_player_id" in pbp.columns:
        recv = pbp[pbp["receiver_player_id"].notna() & is_pass].copy()
        if not recv.empty:
            recv["player_id"] = recv["receiver_player_id"].astype(str)
            recv["targets"] = 1.0
            recv["receptions"] = _flag(recv, "complete_pass")
            recv["receiving_yards"] = _flag(recv, "receiving_yards")
            # pass_touchdown is only set on completions, so it attributes cleanly to the
            # receiver (unlike `touchdown`, which also fires on defensive return TDs).
            recv["receiving_tds"] = _flag(recv, "pass_touchdown")
            frames.append(
                recv.groupby([*_GAME_KEYS, "player_id"], dropna=True)[
                    ["targets", "receptions", "receiving_yards", "receiving_tds"]
                ].sum()
            )

    if "rusher_player_id" in pbp.columns:
        rush = pbp[pbp["rusher_player_id"].notna() & is_rush].copy()
        if not rush.empty:
            rush["player_id"] = rush["rusher_player_id"].astype(str)
            rush["carries"] = 1.0
            rush["rushing_yards"] = _flag(rush, "rushing_yards")
            rush["rushing_tds"] = _flag(rush, "rush_touchdown")
            frames.append(
                rush.groupby([*_GAME_KEYS, "player_id"], dropna=True)[
                    ["carries", "rushing_yards", "rushing_tds"]
                ].sum()
            )

    if "passer_player_id" in pbp.columns:
        pas = pbp[pbp["passer_player_id"].notna() & is_pass & ~is_sack].copy()
        if not pas.empty:
            pas["player_id"] = pas["passer_player_id"].astype(str)
            pas["attempts"] = 1.0
            pas["passing_yards"] = _flag(pas, "passing_yards")
            pas["passing_tds"] = _flag(pas, "pass_touchdown")
            frames.append(
                pas.groupby([*_GAME_KEYS, "player_id"], dropna=True)[
                    ["attempts", "passing_yards", "passing_tds"]
                ].sum()
            )

    if not frames:
        return pd.DataFrame()

    # The team a player was on *for this game*, which is not the same as his current team
    # once he changes clubs — the backfit needs the historical one.
    team_frames: list[pd.DataFrame] = []
    for role_col in ("receiver_player_id", "rusher_player_id", "passer_player_id"):
        if role_col in pbp.columns and "posteam" in pbp.columns:
            sub = pbp.loc[pbp[role_col].notna(), [*_GAME_KEYS, role_col, "posteam"]].copy()
            sub = sub.rename(columns={role_col: "player_id", "posteam": "team"})
            sub["player_id"] = sub["player_id"].astype(str)
            team_frames.append(sub)

    stats = pd.concat(frames, axis=1).fillna(0.0)
    # Duplicate column names cannot happen across roles, but be defensive about it.
    stats = stats.loc[:, ~stats.columns.duplicated()]
    stats["anytime_td"] = (
        (stats.get("receiving_tds", 0.0) + stats.get("rushing_tds", 0.0)) >= 1
    ).astype(float)
    stats = stats.reset_index()

    if team_frames:
        teams = pd.concat(team_frames).drop_duplicates([*_GAME_KEYS, "player_id"])
        stats = stats.merge(teams, on=[*_GAME_KEYS, "player_id"], how="left")
    return stats


def actual_for_market(stats_row: pd.Series | dict[str, Any], market: str) -> float | None:
    """Pull the settling value for one market out of a player-game stat row."""
    market = str(market).strip()
    if market == ANYTIME_TD_MARKET:
        col = "anytime_td"
    else:
        col = (
            RECEIVING_MARKETS.get(market)
            or RUSHING_MARKETS.get(market)
            or PASSING_MARKETS.get(market)
        )
    if col is None:
        return None
    value = stats_row.get(col)
    if value is None or pd.isna(value):
        return None
    return float(value)


def is_prop_play(play: dict[str, Any]) -> bool:
    return play.get("play_type") == "prop" or str(play.get("market") or "").startswith("player_")


class PropActuals:
    """Resolves a ledger prop play to the stat line that settles it.

    Distinguishes "play-by-play has not caught up yet" from "the player recorded nothing
    in a game we do have", because the first must stay pending and the second is a void —
    books refund props when the player doesn't take the field, and a receiver who was
    inactive is indistinguishable from one who played and was never targeted.
    """

    def __init__(self, pbp: pd.DataFrame | None = None) -> None:
        if pbp is None:
            pbp = load_pbp()
        self._names = name_to_player_ids()
        self._stats: dict[tuple[str, str], dict[str, Any]] = {}
        self._players_by_game: dict[str, set[str]] = {}
        self._game_ids: dict[tuple[Any, Any, str, str], str] = {}

        if pbp.empty:
            return

        stats = player_game_stats(pbp)
        for row in stats.to_dict("records"):
            gid = str(row["game_id"])
            pid = str(row["player_id"])
            self._stats[(gid, pid)] = row
            self._players_by_game.setdefault(gid, set()).add(pid)

        cols = [c for c in ("season", "week", "game_id", "home_team", "away_team") if c in pbp.columns]
        if {"game_id", "home_team", "away_team"}.issubset(cols):
            for row in pbp[cols].drop_duplicates("game_id").to_dict("records"):
                key = (
                    row.get("season"),
                    row.get("week"),
                    str(row.get("away_team")),
                    str(row.get("home_team")),
                )
                self._game_ids[key] = str(row["game_id"])

    def _find_game(self, play: dict[str, Any]) -> str | None:
        away = str(play.get("away_team") or "")
        home = str(play.get("home_team") or "")
        season = play.get("season")
        week = play.get("week")
        direct = self._game_ids.get((season, week, away, home))
        if direct:
            return direct
        # Ledger rows do not always carry season/week; fall back to the team pair, and
        # only accept it when it is unambiguous.
        matches = {
            gid
            for (s, _w, a, h), gid in self._game_ids.items()
            if a == away and h == home and (season is None or s == season)
        }
        return next(iter(matches)) if len(matches) == 1 else None

    def value_for(self, play: dict[str, Any]) -> tuple[str, float | None]:
        """Returns (status, value) where status is 'ok', 'void', or 'unknown'."""
        market = str(play.get("market") or "")
        if market not in SETTLEABLE_MARKETS:
            return "unknown", None
        game_id = self._find_game(play)
        if game_id is None:
            return "unknown", None

        candidates = self._names.get(_player_key(str(play.get("player_name") or "")), [])
        played = self._players_by_game.get(game_id, set())
        matched = [pid for pid in candidates if pid in played]
        if len(matched) != 1:
            # Either the player recorded nothing in this game, or the name is ambiguous.
            return "void", None
        value = actual_for_market(self._stats[(game_id, matched[0])], market)
        return ("ok", value) if value is not None else ("void", None)


def name_to_player_ids() -> dict[str, list[str]]:
    """Normalized display name → gsis ids.

    A name can map to more than one id (there have been several Mike Williamses), so
    callers disambiguate by intersecting with the ids that actually played in the game.
    """
    players = load_players()
    if players.empty:
        return {}
    out: dict[str, list[str]] = {}
    for row in players.itertuples(index=False):
        pid = str(getattr(row, "gsis_id", "") or "")
        name = str(getattr(row, "display_name", "") or "").strip()
        if not pid or not name:
            continue
        out.setdefault(_player_key(name), []).append(pid)
    return out
