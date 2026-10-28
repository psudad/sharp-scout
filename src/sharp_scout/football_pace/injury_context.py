"""Walk-forward injury data for NFL backtests."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from sharp_scout.data.cfbfastr import load_cfb_pbp
from sharp_scout.data.nfl_injuries import injuries_for_team_week, load_nfl_injuries
from sharp_scout.data.nflfastr import load_pbp
from sharp_scout.football_pace.games import PaceGame
from sharp_scout.football_pace.player_value import (
    PlayerValueTracker,
    attach_nflverse_positions,
    build_ncaaf_game_touch_index,
    build_nfl_game_touch_index,
)


@dataclass
class InjuryBacktestContext:
    sport: str
    tracker: PlayerValueTracker = field(default_factory=lambda: PlayerValueTracker("nfl"))
    touch_by_game: dict[str, list[tuple[str, str, float]]] = field(default_factory=dict)
    injuries_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    historical_injuries: bool = False

    def injuries_for(self, g: PaceGame) -> tuple[list[dict], list[dict]]:
        if not self.historical_injuries or self.injuries_df.empty:
            return [], []
        home = injuries_for_team_week(self.injuries_df, season=g.season, week=g.week, team=g.home)
        away = injuries_for_team_week(self.injuries_df, season=g.season, week=g.week, team=g.away)
        for row in home + away:
            self.tracker.set_position(row["team"], row["player"], row.get("position") or "")
        return home, away

    def roster_names(self, team: str) -> list[str]:
        team = team.upper()
        names: list[str] = []
        for (t, _key), _ in self.tracker.player_touches.items():
            if t == team:
                names.append(_key)
        for (t, _key) in self.tracker.roster_positions:
            if t == team:
                names.append(_key)
        return names


def build_injury_context(sport: str, seasons: list[int]) -> InjuryBacktestContext:
    ctx = InjuryBacktestContext(sport=sport, tracker=PlayerValueTracker(sport))
    if sport == "nfl":
        pbp = load_pbp(seasons)
        ctx.touch_by_game = build_nfl_game_touch_index(pbp)
        ctx.injuries_df = load_nfl_injuries(seasons)
        ctx.historical_injuries = not ctx.injuries_df.empty
        attach_nflverse_positions(ctx.tracker)
    elif sport == "ncaaf":
        pbp = load_cfb_pbp(seasons)
        ctx.touch_by_game = build_ncaaf_game_touch_index(pbp)
        ctx.historical_injuries = False
    return ctx
