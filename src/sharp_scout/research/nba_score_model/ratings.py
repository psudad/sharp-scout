"""Walk-forward team efficiency ratings for NBA score projection (research)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class ModelParams:
    recency_half_life_days: float = 45.0
    shrink_games: float = 12.0  # prior blend early season
    prior_carry: float = 0.55  # weight on last season end state
    hca_points: float = 2.8
    b2b_penalty: float = 1.6
    league_pace: float = 100.0
    league_ppp: float = 1.12  # pts per poss baseline
    margin_sd_base: float = 11.5
    total_sd_base: float = 15.0


@dataclass
class TeamState:
    off_ppp: float = 1.12
    def_ppp: float = 1.12
    pace: float = 100.0
    games: int = 0
    last_date: datetime | None = None


@dataclass
class RatingEngine:
    params: ModelParams
    teams: dict[str, TeamState] = field(default_factory=dict)
    prior_end: dict[str, TeamState] = field(default_factory=dict)
    margin_residuals: list[float] = field(default_factory=list)
    total_residuals: list[float] = field(default_factory=list)

    def _team(self, code: str) -> TeamState:
        if code not in self.teams:
            base = self.prior_end.get(code)
            if base:
                self.teams[code] = TeamState(
                    off_ppp=base.off_ppp,
                    def_ppp=base.def_ppp,
                    pace=base.pace,
                    games=0,
                )
            else:
                self.teams[code] = TeamState()
        return self.teams[code]

    def _weight(self, days_ago: float) -> float:
        hl = max(self.params.recency_half_life_days, 1.0)
        return 0.5 ** (days_ago / hl)

    def project(
        self,
        home: str,
        away: str,
        *,
        game_date: datetime,
        home_rest: int | None = None,
        away_rest: int | None = None,
    ) -> dict[str, float]:
        p = self.params
        th, ta = self._team(home), self._team(away)
        shrink = min(1.0, (th.games + ta.games) / (2.0 * p.shrink_games))
        h_off = (1 - shrink) * p.league_ppp + shrink * th.off_ppp
        h_def = (1 - shrink) * p.league_ppp + shrink * th.def_ppp
        a_off = (1 - shrink) * p.league_ppp + shrink * ta.off_ppp
        a_def = (1 - shrink) * p.league_ppp + shrink * ta.def_ppp
        pace = (th.pace + ta.pace) / 2.0 if th.games and ta.games else p.league_pace

        home_pts = pace * (h_off + a_def) / 2.0 + p.hca_points / 2.0
        away_pts = pace * (a_off + h_def) / 2.0 - p.hca_points / 2.0
        if home_rest is not None and home_rest <= 1:
            home_pts -= p.b2b_penalty
        if away_rest is not None and away_rest <= 1:
            away_pts -= p.b2b_penalty

        margin = home_pts - away_pts
        total = home_pts + away_pts
        sd_m = self._sd(self.margin_residuals, p.margin_sd_base)
        sd_t = self._sd(self.total_residuals, p.total_sd_base)
        return {
            "home_pts": home_pts,
            "away_pts": away_pts,
            "margin": margin,
            "total": total,
            "sd_margin": sd_m,
            "sd_total": sd_t,
            "shrink": shrink,
        }

    def observe(self, game: dict[str, Any]) -> None:
        home, away = game["home"], game["away"]
        hs, as_ = float(game["home_pts"]), float(game["away_pts"])
        dt: datetime = game["date"]
        poss = max((hs + as_) / (2.0 * self.params.league_ppp), 90.0)
        h_off_obs = hs / poss
        a_off_obs = as_ / poss
        h_def_obs = as_ / poss
        a_def_obs = hs / poss

        th, ta = self._team(home), self._team(away)
        for team, off_obs, def_obs, state in (
            (home, h_off_obs, h_def_obs, th),
            (away, a_off_obs, a_def_obs, ta),
        ):
            days = (dt - state.last_date).days if state.last_date else 30.0
            w = self._weight(max(days, 0.5))
            state.off_ppp = (1 - w) * state.off_ppp + w * off_obs
            state.def_ppp = (1 - w) * state.def_ppp + w * def_obs
            state.pace = (1 - w) * state.pace + w * poss
            state.games += 1
            state.last_date = dt

    def snapshot_season_end(self) -> None:
        self.prior_end = {
            k: TeamState(v.off_ppp, v.def_ppp, v.pace, v.games, v.last_date) for k, v in self.teams.items()
        }

    def new_season(self) -> None:
        carry = self.params.prior_carry
        for code, end in self.prior_end.items():
            self.teams[code] = TeamState(
                off_ppp=carry * end.off_ppp + (1 - carry) * self.params.league_ppp,
                def_ppp=carry * end.def_ppp + (1 - carry) * self.params.league_ppp,
                pace=carry * end.pace + (1 - carry) * self.params.league_pace,
                games=0,
                last_date=None,
            )

    @staticmethod
    def _sd(residuals: list[float], base: float) -> float:
        if len(residuals) < 30:
            return base
        m = sum(residuals) / len(residuals)
        var = sum((x - m) ** 2 for x in residuals[-400:]) / max(len(residuals[-400:]) - 1, 1)
        return max(math.sqrt(var), base * 0.85)


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def p_cover_home(proj_margin: float, close_spread_home: float, sd: float) -> float:
    """Home covers if margin + spread > 0."""
    if sd <= 0:
        return 0.5
    z = (proj_margin + close_spread_home) / sd
    return normal_cdf(z)


def p_over(proj_total: float, close_total: float, sd: float) -> float:
    if sd <= 0:
        return 0.5
    z = (proj_total - close_total) / sd
    return normal_cdf(z)
