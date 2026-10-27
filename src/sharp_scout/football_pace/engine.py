"""Walk-forward pace × efficiency projection engine (football analog of NBA score model)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from sharp_scout.football_pace.config import SportPaceConfig


@dataclass
class TeamPrior:
    off_ppp: float
    def_ppp: float
    pace: float


@dataclass
class PaceEngine:
    """Team tempo (offensive plays/game) and points-per-play offense/defense."""

    config: SportPaceConfig
    team_off: dict[str, float] = field(default_factory=dict)
    team_def: dict[str, float] = field(default_factory=dict)
    team_pace: dict[str, float] = field(default_factory=dict)
    team_games: dict[str, int] = field(default_factory=dict)
    season_priors: dict[str, TeamPrior] = field(default_factory=dict)
    end_season_priors: dict[str, TeamPrior] = field(default_factory=dict)
    margin_residuals: list[float] = field(default_factory=list)
    total_residuals: list[float] = field(default_factory=list)

    @property
    def league_ppp(self) -> float:
        return self.config.league_pts_per_play

    @property
    def league_pace(self) -> float:
        return self.config.league_plays_per_game

    def _prior(self, team: str) -> TeamPrior:
        if team in self.season_priors:
            return self.season_priors[team]
        return TeamPrior(
            off_ppp=self.league_ppp,
            def_ppp=self.league_ppp,
            pace=self.league_pace,
        )

    def _effective(self, team: str, kind: str) -> float:
        prior = self._prior(team)
        g = self.team_games.get(team, 0)
        w = min(1.0, g / max(self.config.prior_decay_games, 1.0))
        if kind == "off":
            raw = self.team_off.get(team, prior.off_ppp)
            return w * raw + (1 - w) * prior.off_ppp
        if kind == "def":
            raw = self.team_def.get(team, prior.def_ppp)
            return w * raw + (1 - w) * prior.def_ppp
        raw = self.team_pace.get(team, prior.pace)
        return w * raw + (1 - w) * prior.pace

    def project(self, home: str, away: str) -> dict[str, float]:
        """Project points, margin, total; HCA shifts margin only (totals unchanged)."""
        lp = self.league_ppp
        h_off = self._effective(home, "off")
        a_off = self._effective(away, "off")
        h_def = self._effective(home, "def")
        a_def = self._effective(away, "def")
        h_pace = self._effective(home, "pace")
        a_pace = self._effective(away, "pace")

        home_ppp = h_off * a_def / lp
        away_ppp = a_off * h_def / lp
        home_pts_base = h_pace * home_ppp
        away_pts_base = a_pace * away_ppp

        hca = self.config.hca_points
        home_pts = home_pts_base + hca / 2.0
        away_pts = away_pts_base - hca / 2.0
        margin = home_pts - away_pts
        total = home_pts_base + away_pts_base
        return {
            "home_pts": home_pts,
            "away_pts": away_pts,
            "margin": margin,
            "total": total,
            "home_plays": h_pace,
            "away_plays": a_pace,
            "home_ppp": home_ppp,
            "away_ppp": away_ppp,
            "sd_margin": self._sd(self.margin_residuals, base=13.5),
            "sd_total": self._sd(self.total_residuals, base=10.5),
        }

    def observe(
        self,
        *,
        home: str,
        away: str,
        home_plays: float,
        away_plays: float,
        home_pts: float,
        away_pts: float,
        game_date: datetime | None = None,
    ) -> None:
        """Update team rates from one completed game (walk-forward caller gates order)."""
        proj = self.project(home, away)
        act_m = home_pts - away_pts
        self.margin_residuals.append(act_m - proj["margin"])
        self.total_residuals.append(home_pts + away_pts - proj["total"])

        for team, plays, pts, opp_pts in (
            (home, home_plays, home_pts, away_pts),
            (away, away_plays, away_pts, home_pts),
        ):
            if plays <= 0:
                continue
            ppp_off = pts / plays
            ppp_def = opp_pts / plays
            g = self.team_games.get(team, 0) + 1
            self.team_games[team] = g
            w = min(1.0, 2.0 / max(g, 1))
            self.team_off[team] = (1 - w) * self.team_off.get(team, self.league_ppp) + w * ppp_off
            self.team_def[team] = (1 - w) * self.team_def.get(team, self.league_ppp) + w * ppp_def
            self.team_pace[team] = (1 - w) * self.team_pace.get(team, self.league_pace) + w * plays

    def end_season(self) -> None:
        reg = self.config.prior_regress_frac
        lp, lpace = self.league_ppp, self.league_pace
        priors: dict[str, TeamPrior] = {}
        teams = set(self.team_off) | set(self.team_def) | set(self.team_pace)
        for team in teams:
            priors[team] = TeamPrior(
                off_ppp=(1 - reg) * self.team_off.get(team, lp) + reg * lp,
                def_ppp=(1 - reg) * self.team_def.get(team, lp) + reg * lp,
                pace=(1 - reg) * self.team_pace.get(team, lpace) + reg * lpace,
            )
        self.end_season_priors = priors
        self.season_priors = dict(priors)
        self.team_games = {t: 0 for t in self.team_games}
        self.margin_residuals = []
        self.total_residuals = []

    def start_new_season(self) -> None:
        self.season_priors = dict(self.end_season_priors)
        for team, p in self.season_priors.items():
            self.team_off[team] = p.off_ppp
            self.team_def[team] = p.def_ppp
            self.team_pace[team] = p.pace

    def _sd(self, residuals: list[float], *, base: float) -> float:
        if len(residuals) < 25:
            return base
        tail = residuals[-400:]
        m = sum(tail) / len(tail)
        var = sum((x - m) ** 2 for x in tail) / max(len(tail) - 1, 1)
        return max(math.sqrt(var), base * 0.85)
