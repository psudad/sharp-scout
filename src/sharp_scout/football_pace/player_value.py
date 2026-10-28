"""Player importance from current-season usage (PBP touches + roster position)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from sharp_scout.data.nflfastr import load_players, nfl_rating_plays
from sharp_scout.utils.odds import normalize_team

OFF_POSITION_CAP: dict[str, float] = {
    "QB": 5.5,
    "RB": 2.8,
    "FB": 1.5,
    "WR": 3.2,
    "TE": 2.4,
    "T": 1.9,
    "G": 1.7,
    "C": 1.7,
    "OL": 1.8,
    "OT": 1.9,
    "OG": 1.7,
}

DEF_POSITION_CAP: dict[str, float] = {
    "CB": 2.6,
    "S": 2.2,
    "FS": 2.2,
    "SS": 2.2,
    "LB": 2.6,
    "ILB": 2.4,
    "OLB": 2.5,
    "EDGE": 3.0,
    "DE": 2.9,
    "DT": 2.2,
    "NT": 2.0,
    "DL": 2.3,
}


def _pos_group(pos: str) -> str:
    p = (pos or "").upper().strip()
    if p in ("QB", "RB", "WR", "TE", "FB"):
        return p
    if p in ("T", "OT", "G", "OG", "C", "OL"):
        return "OL"
    if p in ("DE", "EDGE"):
        return "EDGE"
    if p in ("FS", "SS", "S"):
        return "S"
    if p in ("ILB", "OLB", "LB"):
        return "LB"
    if p in ("CB", "DB"):
        return "CB"
    if p in ("DT", "NT", "DL"):
        return "DL"
    return p


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


@dataclass
class PlayerValueTracker:
    """Walk-forward touch counts → expected point loss if player unavailable."""

    sport: str
    team_touches: dict[str, float] = field(default_factory=dict)
    player_touches: dict[tuple[str, str], float] = field(default_factory=dict)
    player_position: dict[tuple[str, str], str] = field(default_factory=dict)
    roster_positions: dict[tuple[str, str], str] = field(default_factory=dict)
    roster_depth: dict[tuple[str, str], int] = field(default_factory=dict)

    def seed_roster(self, team: str, roster_rows: list[dict]) -> None:
        team = normalize_team(team, self.sport)
        for row in roster_rows:
            name = _name_key(str(row.get("player") or ""))
            if not name:
                continue
            pos = str(row.get("position") or "")
            key = (team, name)
            self.roster_positions[key] = pos
            if row.get("depth_rank") is not None:
                self.roster_depth[key] = int(row["depth_rank"])

    def observe_game_touches(self, *, game_id: str, touches: list[tuple[str, str, float]]) -> None:
        for team, player, n in touches:
            team = normalize_team(team, self.sport)
            pk = (team, _name_key(player))
            self.player_touches[pk] = self.player_touches.get(pk, 0.0) + float(n)
            self.team_touches[team] = self.team_touches.get(team, 0.0) + float(n)
            if pk not in self.player_position and pk in self.roster_positions:
                self.player_position[pk] = self.roster_positions[pk]

    def set_position(self, team: str, player: str, position: str) -> None:
        key = (normalize_team(team, self.sport), _name_key(player))
        if position:
            self.player_position[key] = position

    def touch_share(self, team: str, player: str) -> float:
        team = normalize_team(team, self.sport)
        pk = (team, _name_key(player))
        tot = self.team_touches.get(team, 0.0)
        if tot <= 0:
            return 0.0
        return min(self.player_touches.get(pk, 0.0) / tot, 1.0)

    def off_loss_pts(self, team: str, player: str, position: str | None = None) -> float:
        pos = _pos_group(position or self.player_position.get((normalize_team(team, self.sport), _name_key(player)), ""))
        cap = OFF_POSITION_CAP.get(pos, 1.2 if pos in OFF_POSITION_CAP else 0.8)
        depth = self.roster_depth.get((normalize_team(team, self.sport), _name_key(player)), 1)
        if depth > 2 and pos not in ("QB", "OL", "T", "G", "C"):
            cap *= 0.55
        share = self.touch_share(team, player)
        if share <= 0 and depth == 1:
            share = 0.35
        return cap * share

    def def_loss_pts(self, team: str, player: str, position: str | None = None) -> float:
        pos = _pos_group(position or self.player_position.get((normalize_team(team, self.sport), _name_key(player)), ""))
        cap = DEF_POSITION_CAP.get(pos, 1.0)
        depth = self.roster_depth.get((normalize_team(team, self.sport), _name_key(player)), 2)
        if depth > 2:
            cap *= 0.5
        elif depth == 1:
            cap *= 1.0
        else:
            cap *= 0.75
        return cap * (0.45 + 0.55 * min(self.touch_share(team, player) * 3.0, 1.0))


def build_nfl_game_touch_index(pbp: pd.DataFrame) -> dict[str, list[tuple[str, str, float]]]:
    """game_id -> [(team, player_name, touch_count)]."""
    if pbp.empty:
        return {}
    df = nfl_rating_plays(pbp)
    out: dict[str, list[tuple[str, str, float]]] = {}
    for gid, grp in df.groupby("game_id", sort=False):
        tallies: dict[tuple[str, str], float] = {}
        for _, row in grp.iterrows():
            team = str(row.get("posteam") or "")
            if not team:
                continue
            for col in ("passer_player_name", "rusher_player_name", "receiver_player_name"):
                name = row.get(col)
                if isinstance(name, str) and name.strip():
                    k = (team, name.strip())
                    tallies[k] = tallies.get(k, 0.0) + 1.0
        out[str(gid)] = [(t, p, n) for (t, p), n in tallies.items()]
    return out


def build_ncaaf_game_touch_index(pbp: pd.DataFrame) -> dict[str, list[tuple[str, str, float]]]:
    if pbp.empty:
        return {}
    from sharp_scout.data.cfbfastr import cfb_rating_plays

    df = cfb_rating_plays(pbp)[0]
    out: dict[str, list[tuple[str, str, float]]] = {}
    for gid, grp in df.groupby("game_id", sort=False):
        tallies: dict[tuple[str, str], float] = {}
        for _, row in grp.iterrows():
            team = str(row.get("posteam") or "")
            if not team:
                continue
            for col in ("passer_player_name", "rusher_player_name"):
                name = row.get(col)
                if isinstance(name, str) and name.strip():
                    k = (team, name.strip())
                    tallies[k] = tallies.get(k, 0.0) + 1.0
        out[str(gid)] = [(t, p, n) for (t, p), n in tallies.items()]
    return out


def attach_nflverse_positions(tracker: PlayerValueTracker) -> None:
    players = load_players()
    if players.empty:
        return
    for row in players.itertuples():
        team = getattr(row, "latest_team", None)
        name = getattr(row, "display_name", None) or getattr(row, "football_name", None)
        pos = getattr(row, "position", None) or getattr(row, "position_group", None)
        if team and name:
            tracker.set_position(str(team), str(name), str(pos or ""))


def match_player(name: str, candidates: list[str]) -> str | None:
    """Match injury name to roster/PBP name on same team."""
    key = _name_key(name)
    if not key:
        return None
    for c in candidates:
        if _name_key(c) == key:
            return c
    last = key.split()[-1] if key.split() else key
    for c in candidates:
        ck = _name_key(c)
        if ck.endswith(last) or last in ck:
            return c
    return None
