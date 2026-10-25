"""Walk-forward possession ridge model with staged features (research v2)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from sharp_scout.nba.score_model.teams_geo import ALTITUDE_TEAMS, travel_miles


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


LEAGUE_ORTG = 112.0
LEAGUE_PACE = 100.0


@dataclass
class V2Params:
    ridge_lambda: float = 2.0
    recency_half_life_days: float = 45.0
    hca_points: float = 2.25
    prior_regress_frac: float = 1.0 / 3.0
    prior_decay_games: float = 18.0
    b2b_penalty: float = 1.25
    rest_slope: float = 0.15  # pts per rest day below 2
    three_in_four_penalty: float = 1.0
    travel_per_500mi: float = 0.35
    altitude_penalty: float = 1.1
    player_ppm_scale: float = 0.85
    history_cap: int = 900
    refit_every_games: int = 4
    margin_sd_base: float = 11.0
    total_sd_base: float = 14.5


@dataclass
class TeamPrior:
    off: float = LEAGUE_ORTG
    def_: float = LEAGUE_ORTG
    pace: float = LEAGUE_PACE


@dataclass
class HistRow:
    date: datetime
    home: str
    away: str
    home_ortg: float
    away_ortg: float
    pace: float
    home_rest: int
    away_rest: int
    home_b2b: float
    away_b2b: float
    home_3in4: float
    away_3in4: float
    home_travel: float
    away_travel: float
    home_alt: float
    away_alt: float
    weight: float


@dataclass
class PlayerTracker:
    """Rolling minutes / points per minute by player name (approximate)."""

    mpg: dict[str, float] = field(default_factory=dict)
    ppm: dict[str, float] = field(default_factory=dict)
    games: dict[str, int] = field(default_factory=dict)

    def observe_game(self, player_mins: dict[str, float], *, team_pts: float, team_poss: float) -> None:
        if not player_mins:
            return
        total_mins = sum(player_mins.values()) or 1.0
        for name, mins in player_mins.items():
            g = self.games.get(name, 0) + 1
            self.games[name] = g
            w = min(1.0, 2.0 / g)
            self.mpg[name] = (1 - w) * self.mpg.get(name, mins) + w * mins
            pts_share = (mins / total_mins) * team_pts
            ppm = pts_share / max(mins, 1.0)
            self.ppm[name] = (1 - w) * self.ppm.get(name, ppm) + w * ppm

    def missing_pts(self, player_mins: dict[str, float], *, min_mpg: float = 18.0) -> float:
        """Players with 0 minutes who normally play — optimistic injury proxy."""
        if not player_mins:
            return 0.0
        missing = 0.0
        active = {k for k, v in player_mins.items() if v > 0.5}
        for name, avg_m in self.mpg.items():
            if avg_m < min_mpg or self.games.get(name, 0) < 12:
                continue
            if name not in active:
                missing += avg_m * self.ppm.get(name, 0.0)
        return missing


@dataclass
class V2Engine:
    params: V2Params
    stage: int = 1
    team_off: dict[str, float] = field(default_factory=dict)
    team_def: dict[str, float] = field(default_factory=dict)
    team_pace: dict[str, float] = field(default_factory=dict)
    season_priors: dict[str, TeamPrior] = field(default_factory=dict)
    end_season_priors: dict[str, TeamPrior] = field(default_factory=dict)
    history: list[HistRow] = field(default_factory=list)
    margin_residuals: list[float] = field(default_factory=list)
    total_residuals: list[float] = field(default_factory=list)
    team_games: dict[str, int] = field(default_factory=dict)
    player_track: dict[str, PlayerTracker] = field(default_factory=dict)
    _team_index: dict[str, int] = field(default_factory=dict)
    _cached_off: dict[str, float] = field(default_factory=dict)
    _cached_def: dict[str, float] = field(default_factory=dict)
    _ridge_intercept: float = LEAGUE_ORTG
    _refit_cooldown: int = 0

    def _idx(self, team: str) -> int:
        if team not in self._team_index:
            self._team_index[team] = len(self._team_index)
        return self._team_index[team]

    def _prior_team(self, team: str) -> TeamPrior:
        if self.stage >= 2 and team in self.season_priors:
            return self.season_priors[team]
        return TeamPrior()

    def _effective_rating(self, team: str, kind: str) -> float:
        g = self.team_games.get(team, 0)
        prior = self._prior_team(team)
        if kind == "off":
            raw = self.team_off.get(team, prior.off)
            prior_val = prior.off
        elif kind == "def":
            raw = self.team_def.get(team, prior.def_)
            prior_val = prior.def_
        else:
            raw = self.team_pace.get(team, prior.pace)
            prior_val = prior.pace
        if self.stage < 2:
            return raw
        w = min(1.0, g / max(self.params.prior_decay_games, 1.0))
        return w * raw + (1 - w) * prior_val

    def _schedule_adj(
        self,
        home: str,
        away: str,
        *,
        home_rest: int | None,
        away_rest: int | None,
        home_3in4: bool,
        away_3in4: bool,
        home_travel_mi: float,
        away_travel_mi: float,
    ) -> tuple[float, float]:
        if self.stage < 3:
            return 0.0, 0.0
        p = self.params
        h_adj = p.hca_points / 2.0
        a_adj = -p.hca_points / 2.0
        if home_rest is not None and home_rest <= 1:
            h_adj -= p.b2b_penalty
        if away_rest is not None and away_rest <= 1:
            a_adj -= p.b2b_penalty
        if home_rest is not None and home_rest >= 2:
            h_adj += min(home_rest - 1, 3) * p.rest_slope
        if away_rest is not None and away_rest >= 2:
            a_adj += min(away_rest - 1, 3) * p.rest_slope
        if home_3in4:
            h_adj -= p.three_in_four_penalty
        if away_3in4:
            a_adj -= p.three_in_four_penalty
        h_adj -= (home_travel_mi / 500.0) * p.travel_per_500mi
        a_adj -= (away_travel_mi / 500.0) * p.travel_per_500mi
        if home in ALTITUDE_TEAMS:
            a_adj -= p.altitude_penalty
        if away in ALTITUDE_TEAMS:
            h_adj += p.altitude_penalty * 0.35
        return h_adj, a_adj

    def _fit_ridge(self) -> tuple[dict[str, float], dict[str, float]]:
        """Weighted ridge: ORtg ~ off_team + def_opponent (+ optional schedule in stage 3)."""
        if self._cached_off and self._refit_cooldown > 0:
            self._refit_cooldown -= 1
            return self._cached_off, self._cached_def
        p = self.params
        hist = self.history[-p.history_cap :]
        teams = sorted(self._team_index.keys())
        if len(hist) < 60 or not teams:
            return {}, {}
        tmap = {t: i for i, t in enumerate(teams)}
        n_t = len(teams)
        sched_cols = 0  # schedule handled in projection layer (stage 3+), not ridge
        # Intercept (unpenalized) + off/def: without μ, ridge shrinks off+def toward 0 and breaks totals.
        n_feat = 1 + 2 * n_t + sched_cols
        rows: list[np.ndarray] = []
        y: list[float] = []
        w: list[float] = []
        for row in hist:
            pairs = (
                (row.home, row.away, row.home_ortg, 1.0, row.home_b2b, row.home_3in4, row.home_travel, row.home_alt),
                (row.away, row.home, row.away_ortg, 0.0, row.away_b2b, row.away_3in4, row.away_travel, row.away_alt),
            )
            for att, opp, ortg, is_home, b2b, three4, trav, alt in pairs:
                feat = np.zeros(n_feat)
                feat[0] = 1.0
                feat[1 + tmap[att]] = 1.0
                feat[1 + n_t + tmap[opp]] = 1.0
                if sched_cols:
                    base = 1 + 2 * n_t
                    feat[base] = is_home
                    feat[base + 1] = b2b
                    feat[base + 2] = three4
                    feat[base + 3] = trav / 1000.0
                    feat[base + 4] = alt
                rows.append(feat)
                y.append(ortg)
                w.append(row.weight)
        X = np.vstack(rows)
        yv = np.array(y)
        wv = np.array(w)
        sw = np.sqrt(wv)[:, None]
        Xw = X * sw
        yw = yv * np.sqrt(wv)
        lam = p.ridge_lambda
        reg = lam * np.eye(n_feat)
        reg[0, 0] = 0.0
        beta = np.linalg.solve(Xw.T @ Xw + reg, Xw.T @ yw)
        intercept = float(beta[0])
        off = {t: float(beta[1 + tmap[t]]) for t in teams}
        def_ = {t: float(beta[1 + n_t + tmap[t]]) for t in teams}
        self._ridge_intercept = intercept
        self._cached_off, self._cached_def = off, def_
        self._refit_cooldown = max(p.refit_every_games - 1, 0)
        return off, def_

    def project(
        self,
        home: str,
        away: str,
        *,
        game_date: datetime,
        home_rest: int | None = None,
        away_rest: int | None = None,
        home_3in4: bool = False,
        away_3in4: bool = False,
        home_travel_mi: float = 0.0,
        away_travel_mi: float = 0.0,
        home_player_mins: dict[str, float] | None = None,
        away_player_mins: dict[str, float] | None = None,
    ) -> dict[str, float]:
        off_fit, def_fit = self._fit_ridge()

        pace = (self._effective_rating(home, "pace") + self._effective_rating(away, "pace")) / 2.0

        h_off = self._effective_rating(home, "off")
        a_off = self._effective_rating(away, "off")
        h_def_allow = self._effective_rating(home, "def")  # pts allowed per 100
        a_def_allow = self._effective_rating(away, "def")

        mu = getattr(self, "_ridge_intercept", LEAGUE_ORTG)
        if off_fit and home in off_fit and away in off_fit:
            # Ridge: ORtg ~ μ + off_att + def_opp (μ unpenalized — fixes totals vs raw off+def ridge).
            home_ortg = mu + off_fit[home] + def_fit.get(away, 0.0)
            away_ortg = mu + off_fit[away] + def_fit.get(home, 0.0)
        else:
            # Multiplicative matchup when ridge not ready (team_def is allowed ORtg, not ridge coeff).
            home_ortg = h_off * a_def_allow / LEAGUE_ORTG
            away_ortg = a_off * h_def_allow / LEAGUE_ORTG
        home_pts_base = pace * home_ortg / 100.0
        away_pts_base = pace * away_ortg / 100.0
        h_adj, a_adj = self._schedule_adj(
            home,
            away,
            home_rest=home_rest,
            away_rest=away_rest,
            home_3in4=home_3in4,
            away_3in4=away_3in4,
            home_travel_mi=home_travel_mi,
            away_travel_mi=away_travel_mi,
        )
        # Schedule layer is for margin / sides; close totals already embed pace/fatigue.
        home_pts = home_pts_base + h_adj
        away_pts = away_pts_base + a_adj

        margin = home_pts - away_pts
        total = home_pts_base + away_pts_base

        # Stage 4: optional margin-only injury proxy (does not deflate totals).
        if self.stage >= 4 and home_player_mins and away_player_mins:
            ht = self.player_track.setdefault(home, PlayerTracker())
            at = self.player_track.setdefault(away, PlayerTracker())
            scale = self.params.player_ppm_scale
            home_miss = min(scale * ht.missing_pts(home_player_mins), 8.0)
            away_miss = min(scale * at.missing_pts(away_player_mins), 8.0)
            margin -= home_miss - away_miss
        sd_m = self._sd(self.margin_residuals)
        sd_t = self._sd(self.total_residuals)
        return {
            "home_pts": home_pts,
            "away_pts": away_pts,
            "margin": margin,
            "total": total,
            "sd_margin": sd_m,
            "sd_total": sd_t,
        }

    def observe(self, game: dict[str, Any], *, ctx: dict[str, Any]) -> None:
        home, away = game["home"], game["away"]
        hs, as_ = float(game["home_pts"]), float(game["away_pts"])
        dt: datetime = game["date"]
        poss = float(game.get("game_poss") or game.get("home_poss") or max((hs + as_) / 2.2, 90.0))
        home_ortg = 100.0 * hs / poss
        away_ortg = 100.0 * as_ / poss
        days_w = 1.0
        if self.history:
            days = max((dt - self.history[-1].date).days, 1)
            days_w = 0.5 ** (days / max(self.params.recency_half_life_days, 1.0))
        row = HistRow(
            date=dt,
            home=home,
            away=away,
            home_ortg=home_ortg,
            away_ortg=away_ortg,
            pace=poss,
            home_rest=float(ctx.get("home_rest") or 3),
            away_rest=float(ctx.get("away_rest") or 3),
            home_b2b=1.0 if ctx.get("home_b2b") else 0.0,
            away_b2b=1.0 if ctx.get("away_b2b") else 0.0,
            home_3in4=1.0 if ctx.get("home_3in4") else 0.0,
            away_3in4=1.0 if ctx.get("away_3in4") else 0.0,
            home_travel=float(ctx.get("home_travel_mi") or 0),
            away_travel=float(ctx.get("away_travel_mi") or 0),
            home_alt=1.0 if home in ALTITUDE_TEAMS else 0.0,
            away_alt=1.0 if away in ALTITUDE_TEAMS else 0.0,
            weight=days_w,
        )
        self.history.append(row)
        self._idx(home)
        self._idx(away)
        self.team_games[home] = self.team_games.get(home, 0) + 1
        self.team_games[away] = self.team_games.get(away, 0) + 1
        # Exponential team ORtg summaries (100 * pts/poss), opponent-facing def rating
        for team, ortg, opp_ortg in (
            (home, home_ortg, away_ortg),
            (away, away_ortg, home_ortg),
        ):
            w = min(1.0, 2.0 / max(self.team_games[team], 1))
            self.team_off[team] = (1 - w) * self.team_off.get(team, LEAGUE_ORTG) + w * ortg
            # Defensive quality: points allowed per 100 (opponent ORtg in this game)
            self.team_def[team] = (1 - w) * self.team_def.get(team, LEAGUE_ORTG) + w * opp_ortg
            self.team_pace[team] = (1 - w) * self.team_pace.get(team, LEAGUE_PACE) + w * poss

        if self.stage >= 4:
            hp = game.get("home_player_mins") or {}
            ap = game.get("away_player_mins") or {}
            if hp:
                self.player_track.setdefault(home, PlayerTracker()).observe_game(hp, team_pts=hs, team_poss=poss)
            if ap:
                self.player_track.setdefault(away, PlayerTracker()).observe_game(ap, team_pts=as_, team_poss=poss)

    def end_season(self) -> None:
        priors: dict[str, TeamPrior] = {}
        for team, off in self.team_off.items():
            reg = self.params.prior_regress_frac
            priors[team] = TeamPrior(
                off=(1 - reg) * off + reg * LEAGUE_ORTG,
                def_=(1 - reg) * self.team_def.get(team, LEAGUE_ORTG) + reg * LEAGUE_ORTG,
                pace=(1 - reg) * self.team_pace.get(team, LEAGUE_PACE) + reg * LEAGUE_PACE,
            )
        self.end_season_priors = priors
        self.season_priors = dict(priors)
        self.team_games = {k: 0 for k in self.team_games}
        self.history = []

    def start_new_season(self) -> None:
        if self.stage >= 2:
            self.season_priors = dict(self.end_season_priors)
        self.team_off = {t: p.off for t, p in self.season_priors.items()}
        self.team_def = {t: p.def_ for t, p in self.season_priors.items()}
        self.team_pace = {t: p.pace for t, p in self.season_priors.items()}

    def _sd(self, residuals: list[float]) -> float:
        base = self.params.margin_sd_base
        if len(residuals) < 40:
            return base
        m = sum(residuals[-400:]) / len(residuals[-400:])
        var = sum((x - m) ** 2 for x in residuals[-400:]) / max(len(residuals[-400:]) - 1, 1)
        return max(math.sqrt(var), base * 0.85)


def p_cover_home(proj_margin: float, spread_home: float, sd: float) -> float:
    if sd <= 0:
        return 0.5
    z = (proj_margin + spread_home) / sd
    return normal_cdf(z)


def p_over(proj_total: float, close_total: float, sd: float) -> float:
    if sd <= 0:
        return 0.5
    z = (proj_total - close_total) / sd
    return normal_cdf(z)
