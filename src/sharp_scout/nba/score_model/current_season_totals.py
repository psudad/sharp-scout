"""2026-27 regular-season totals only — no prior-season carryover or blending."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from statistics import mean
from typing import Any

from sharp_scout.nba.score_model.engine import HistRow, LEAGUE_ORTG, LEAGUE_PACE, V2Engine
from sharp_scout.nba.score_model.state import _season_label, _season_start_date

MIN_SPLIT_GAMES = 2


@dataclass
class TeamTotalSample:
    games: int = 0
    pace: list[float] = field(default_factory=list)
    ortg: list[float] = field(default_factory=list)
    drtg: list[float] = field(default_factory=list)
    pace_home: list[float] = field(default_factory=list)
    ortg_home: list[float] = field(default_factory=list)
    drtg_home: list[float] = field(default_factory=list)
    pace_away: list[float] = field(default_factory=list)
    ortg_away: list[float] = field(default_factory=list)
    drtg_away: list[float] = field(default_factory=list)


def _season_for_kickoff(kickoff: datetime) -> str:
    return _season_label(kickoff)


def _hist_in_current_regular_season(
    engine: V2Engine,
    *,
    before: datetime,
) -> list[HistRow]:
    season = _season_for_kickoff(before)
    start = _season_start_date(before)
    out: list[HistRow] = []
    for row in engine.history:
        if row.date >= before:
            continue
        if row.date.date() < start:
            continue
        if _season_label(row.date) != season:
            continue
        out.append(row)
    return out


def _avg(vals: list[float], default: float) -> float:
    return float(mean(vals)) if vals else default


def _pick_split(
    home_vals: list[float],
    away_vals: list[float],
    all_vals: list[float],
    *,
    at_home: bool,
    default: float,
) -> float:
    if at_home and len(home_vals) >= MIN_SPLIT_GAMES:
        return _avg(home_vals, _avg(all_vals, default))
    if not at_home and len(away_vals) >= MIN_SPLIT_GAMES:
        return _avg(away_vals, _avg(all_vals, default))
    return _avg(all_vals, default)


def build_team_samples(hist: list[HistRow]) -> dict[str, TeamTotalSample]:
    teams: dict[str, TeamTotalSample] = {}
    for row in hist:
        for team, ortg, opp_ortg, is_home in (
            (row.home, row.home_ortg, row.away_ortg, True),
            (row.away, row.away_ortg, row.home_ortg, False),
        ):
            s = teams.setdefault(team, TeamTotalSample())
            s.games += 1
            s.pace.append(row.pace)
            s.ortg.append(ortg)
            s.drtg.append(opp_ortg)
            if is_home:
                s.pace_home.append(row.pace)
                s.ortg_home.append(ortg)
                s.drtg_home.append(opp_ortg)
            else:
                s.pace_away.append(row.pace)
                s.ortg_away.append(ortg)
                s.drtg_away.append(opp_ortg)
    return teams


def league_baselines(hist: list[HistRow]) -> tuple[float, float]:
    if not hist:
        return LEAGUE_PACE, LEAGUE_ORTG
    paces = [r.pace for r in hist]
    ortgs = [r.home_ortg for r in hist] + [r.away_ortg for r in hist]
    return _avg(paces, LEAGUE_PACE), _avg(ortgs, LEAGUE_ORTG)


def project_total_current_season(
    engine: V2Engine,
    home: str,
    away: str,
    *,
    game_date: datetime,
) -> dict[str, Any]:
    """Expected total from current-season game logs only (pace × matchup ORtg)."""
    hist = _hist_in_current_regular_season(engine, before=game_date)
    teams = build_team_samples(hist)
    lg_pace, lg_ortg = league_baselines(hist)
    hs = teams.get(home, TeamTotalSample())
    as_ = teams.get(away, TeamTotalSample())

    h_pace = _pick_split(hs.pace_home, hs.pace_away, hs.pace, at_home=True, default=lg_pace)
    a_pace = _pick_split(as_.pace_home, as_.pace_away, as_.pace, at_home=False, default=lg_pace)
    exp_pace = (h_pace + a_pace) / 2.0

    h_off = (
        _pick_split(hs.ortg_home, hs.ortg_away, hs.ortg, at_home=True, default=lg_ortg)
        if hs.games
        else lg_ortg
    )
    a_off = (
        _pick_split(as_.ortg_home, as_.ortg_away, as_.ortg, at_home=False, default=lg_ortg)
        if as_.games
        else lg_ortg
    )
    h_def = (
        _pick_split(hs.drtg_home, hs.drtg_away, hs.drtg, at_home=True, default=lg_ortg)
        if hs.games
        else lg_ortg
    )
    a_def = (
        _pick_split(as_.drtg_home, as_.drtg_away, as_.drtg, at_home=False, default=lg_ortg)
        if as_.games
        else lg_ortg
    )

    home_ortg = h_off * a_def / lg_ortg
    away_ortg = a_off * h_def / lg_ortg
    home_pts = exp_pace * home_ortg / 100.0
    away_pts = exp_pace * away_ortg / 100.0
    total = home_pts + away_pts

    diag = {
        "season": _season_for_kickoff(game_date),
        "league_games": len(hist),
        "league_pace": round(lg_pace, 2),
        "league_ortg": round(lg_ortg, 2),
        "home": {
            "team": home,
            "games": hs.games,
            "pace": round(h_pace, 2),
            "ortg": round(h_off, 2),
            "drtg": round(h_def, 2),
            "home_games": len(hs.pace_home),
            "away_games": len(hs.pace_away),
        },
        "away": {
            "team": away,
            "games": as_.games,
            "pace": round(a_pace, 2),
            "ortg": round(a_off, 2),
            "drtg": round(a_def, 2),
            "home_games": len(as_.pace_home),
            "away_games": len(as_.pace_away),
        },
        "expected_pace": round(exp_pace, 2),
        "home_matchup_ortg": round(home_ortg, 2),
        "away_matchup_ortg": round(away_ortg, 2),
    }
    return {
        "total": round(total, 2),
        "total_home_pts": round(home_pts, 2),
        "total_away_pts": round(away_pts, 2),
        "total_diagnostics": diag,
    }


def project_total_legacy_prior_blend(
    engine: V2Engine,
    home: str,
    away: str,
    *,
    game_date: datetime,
) -> float:
    """Pre-change total (prior-blended pace/ORTG, no schedule on total). For backtests only."""
    _ = game_date
    off_fit, def_fit = engine._fit_ridge()
    pace = (engine._effective_rating(home, "pace") + engine._effective_rating(away, "pace")) / 2.0
    h_off = engine._effective_rating(home, "off")
    a_off = engine._effective_rating(away, "off")
    h_def_allow = engine._effective_rating(home, "def")
    a_def_allow = engine._effective_rating(away, "def")
    mu = getattr(engine, "_ridge_intercept", LEAGUE_ORTG)
    min_team_g = min(engine.team_games.get(home, 0), engine.team_games.get(away, 0))
    ridge_ok = (
        off_fit
        and home in off_fit
        and away in off_fit
        and min_team_g >= engine.params.ridge_min_team_games
    )
    if ridge_ok:
        home_ortg = mu + off_fit[home] + def_fit.get(away, 0.0)
        away_ortg = mu + off_fit[away] + def_fit.get(home, 0.0)
    else:
        home_ortg = h_off * a_def_allow / LEAGUE_ORTG
        away_ortg = a_off * h_def_allow / LEAGUE_ORTG
    home_pts_base = pace * home_ortg / 100.0
    away_pts_base = pace * away_ortg / 100.0
    return round(home_pts_base + away_pts_base, 2)
