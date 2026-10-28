"""Preseason team priors from live ESPN rosters + minutes-weighted player rates (no Odds API)."""

from __future__ import annotations

import logging
from typing import Any

from sharp_scout.nba.franchises import is_nba_franchise
from sharp_scout.nba.player_rates_espn import build_player_rate_rows
from sharp_scout.nba.score_model.engine import LEAGUE_ORTG, LEAGUE_PACE, TeamPrior
from sharp_scout.nba.score_model.player_impact import bpm_proxy_per100, impact_rate_row
from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

# Blend roster-implied team strength with regressed prior-season team ratings.
ROSTER_PRIOR_WEIGHT = 0.55


def _team_aggregate_from_roster(rows: list[dict[str, Any]]) -> dict[str, TeamPrior]:
    """Minutes-weighted BPM proxy → off/def/pace prior per franchise."""
    by_team: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    for row in rows:
        team = normalize_nba_team(str(row.get("team") or ""))
        if not is_nba_franchise(team):
            continue
        adj = impact_rate_row(row)
        mpg = float(adj.get("minutes") or 0)
        if mpg < 6.0:
            continue
        by_team.setdefault(team, []).append((mpg, adj))

    priors: dict[str, TeamPrior] = {}
    for team, weighted in by_team.items():
        total_m = sum(w for w, _ in weighted) or 1.0
        bpm_sum = 0.0
        pace_sum = 0.0
        for mpg, adj in weighted:
            share = mpg / total_m
            bpm_sum += bpm_proxy_per100(adj) * share
            usage = float(adj.get("usage_share") or 0.18)
            pace_sum += (LEAGUE_PACE + (usage - 0.20) * 12.0) * share
        off = LEAGUE_ORTG + bpm_sum * 0.42
        def_ = LEAGUE_ORTG - bpm_sum * 0.28
        priors[team] = TeamPrior(
            off=max(104.0, min(122.0, off)),
            def_=max(104.0, min(122.0, def_)),
            pace=max(96.0, min(104.0, pace_sum)),
        )
    return priors


def blend_priors_with_regressed_season(
    roster_priors: dict[str, TeamPrior],
    regressed: dict[str, TeamPrior],
    *,
    roster_weight: float = ROSTER_PRIOR_WEIGHT,
) -> dict[str, TeamPrior]:
    """Roster-aware preseason prior blended with last season team ratings (1/3 regress)."""
    w = max(0.0, min(1.0, roster_weight))
    teams = set(roster_priors) | set(regressed)
    out: dict[str, TeamPrior] = {}
    for team in teams:
        r = roster_priors.get(team) or TeamPrior()
        s = regressed.get(team) or TeamPrior()
        out[team] = TeamPrior(
            off=w * r.off + (1 - w) * s.off,
            def_=w * r.def_ + (1 - w) * s.def_,
            pace=w * r.pace + (1 - w) * s.pace,
        )
    return out


def build_roster_weighted_priors(
    *,
    regressed_team_priors: dict[str, TeamPrior],
    season_end_year: int,
) -> dict[str, TeamPrior]:
    rows = build_player_rate_rows(season=season_end_year)
    roster = _team_aggregate_from_roster(rows)
    blended = blend_priors_with_regressed_season(roster, regressed_team_priors)
    logger.info(
        "roster priors: %d teams from %d player rows (%.0f%% roster / %.0f%% regressed season)",
        len(blended),
        len(rows),
        ROSTER_PRIOR_WEIGHT * 100,
        (1 - ROSTER_PRIOR_WEIGHT) * 100,
    )
    return blended
