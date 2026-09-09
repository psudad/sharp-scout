"""Historical walk-forward backfit for player props.

Waiting for live props to settle would cost a full season before there is enough data to
calibrate. Instead this reconstructs, week by week, the projection the model *would* have
made using only play-by-play available before that week, then grades it against what
actually happened.

Because historical prop lines and prices are not available in the free feed, lines are
sampled from the model's own distribution at fixed quantiles. That is enough to answer the
calibration question — when the model says 65%, does it happen 65% of the time? — even
though it cannot measure realized ROI.

    python scripts/backfit_props.py --seasons 2023 2024 2025
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

import numpy as np
import pandas as pd

from sharp_scout.config import get_settings
from sharp_scout.data.nflfastr import load_pbp
from sharp_scout.props.actuals import ANYTIME_TD_MARKET, actual_for_market, player_game_stats
from sharp_scout.props.markets import _market_fits
from sharp_scout.props.simulate import CORE_PROP_MARKETS, simulate_prop
from sharp_scout.props.usage import PlayerUsage, apply_game_script, build_usage_profiles

logger = logging.getLogger(__name__)

# Sampling the model's own distribution at these quantiles spreads p_true across roughly
# 0.2–0.8, which is the range real prop pricing lives in.
DEFAULT_QUANTILES = (0.20, 0.35, 0.50, 0.65, 0.80)


def _snap_half(value: float) -> float:
    """Snap to the nearest x.5, the way books post prop lines (avoids pushes entirely)."""
    return float(round(value - 0.5) + 0.5)


def _game_index(pbp: pd.DataFrame) -> pd.DataFrame:
    cols = ["season", "week", "game_id", "home_team", "away_team", "spread_line", "total_line"]
    present = [c for c in cols if c in pbp.columns]
    return pbp[present].drop_duplicates("game_id").reset_index(drop=True)


def run_backfit(
    seasons: list[int] | None = None,
    *,
    quantiles: Iterable[float] = DEFAULT_QUANTILES,
    markets: list[str] | None = None,
    n_sims: int = 2000,
    min_train_weeks: int = 17,
    pbp: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Grade reconstructed weekly projections against actual results.

    Returns records shaped like ledger prop plays (market, p_true, status, ...) so they
    feed straight into the existing calibration and walk-forward machinery.
    """
    settings = get_settings()
    if pbp is None:
        pbp = load_pbp(seasons)
    if pbp.empty:
        logger.warning("No play-by-play — nothing to backfit")
        return []

    markets = markets or settings.prop_market_list or CORE_PROP_MARKETS
    quantiles = list(quantiles)

    stats = player_game_stats(pbp)
    if stats.empty:
        return []
    stat_rows = {
        (str(r["game_id"]), str(r["player_id"])): r for r in stats.to_dict("records")
    }
    players_by_game: dict[str, set[str]] = {}
    for gid, pid in stat_rows:
        players_by_game.setdefault(gid, set()).add(pid)

    games = _game_index(pbp)
    # Chronological order, and skip the earliest weeks so there is history to train on.
    week_keys = sorted({(int(r.season), int(r.week)) for r in games.itertuples()})
    ordered = [k for i, k in enumerate(week_keys) if i >= min_train_weeks]
    logger.info(
        "Backfit: %d candidate weeks, grading %d after %d warmup weeks",
        len(week_keys),
        len(ordered),
        min_train_weeks,
    )

    records: list[dict[str, Any]] = []
    for season, week in ordered:
        prior = pbp[
            (pbp["season"] < season) | ((pbp["season"] == season) & (pbp["week"] < week))
        ]
        if prior.empty:
            continue
        profiles = build_usage_profiles(prior)
        if not profiles:
            continue
        by_pid = {u.player_id: u for u in profiles.values()}

        week_games = games[(games["season"] == season) & (games["week"] == week)]
        for g in week_games.itertuples():
            gid = str(g.game_id)
            played = players_by_game.get(gid)
            if not played:
                continue
            # nflverse spread_line is positive when the home team is favored; the model's
            # home_spread is negative when home is favored.
            spread_line = getattr(g, "spread_line", None)
            total_line = getattr(g, "total_line", None)
            home_spread = -float(spread_line) if pd.notna(spread_line) else 0.0
            total = float(total_line) if pd.notna(total_line) else 45.0

            for pid in played:
                usage = by_pid.get(pid)
                if usage is None:
                    continue
                stat_row = stat_rows[(gid, pid)]
                # Team as of this week comes from the game, not the player's current team —
                # otherwise a player who has since been traded gets the game script for the
                # wrong side.
                game_team = stat_row.get("team")
                is_home = str(game_team) == str(g.home_team)
                team_spread = home_spread if is_home else -home_spread
                scripted = apply_game_script(
                    usage, team_spread=team_spread, team_total=total, is_home=is_home
                )
                records.extend(
                    _grade_player(
                        scripted,
                        stat_row,
                        markets=markets,
                        quantiles=quantiles,
                        n_sims=n_sims,
                        season=season,
                        week=week,
                        game_id=gid,
                        home_team=str(g.home_team),
                        away_team=str(g.away_team),
                        team=str(game_team or usage.team),
                    )
                )
        logger.info("Backfit %s week %s → %d graded records", season, week, len(records))

    return records


def _grade_player(
    usage: PlayerUsage,
    stat_row: dict[str, Any],
    *,
    markets: list[str],
    quantiles: list[float],
    n_sims: int,
    season: int,
    week: int,
    game_id: str,
    home_team: str,
    away_team: str,
    team: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for market in markets:
        if not _market_fits(usage, market):
            continue
        actual = actual_for_market(stat_row, market)
        if actual is None:
            continue
        try:
            sim = simulate_prop(usage, market, n_sims=n_sims)
        except ValueError:
            # No usable baseline for this market — the live pipeline skips it too.
            continue

        if market == ANYTIME_TD_MARKET:
            lines: list[float | None] = [None]
        else:
            lines = sorted(
                {
                    _snap_half(float(np.quantile(sim.samples, q)))
                    for q in quantiles
                    if _snap_half(float(np.quantile(sim.samples, q))) > 0
                }
            )

        for line in lines:
            if line is None:
                p_true = float(np.mean(sim.samples >= 1))
                won = actual >= 1
            else:
                p_true = sim.p_over(line)
                won = actual > line
            # A degenerate probability carries no calibration signal.
            if p_true <= 0.02 or p_true >= 0.98:
                continue
            out.append(
                {
                    "play_type": "prop",
                    "season": season,
                    "week": week,
                    "game_id": game_id,
                    "home_team": home_team,
                    "away_team": away_team,
                    "player_name": usage.player_name,
                    "team": team,
                    "market": market,
                    "side": "over",
                    "line": line,
                    "p_true": round(p_true, 4),
                    "model_mean": round(sim.mean, 2),
                    "actual": actual,
                    "status": "win" if won else "loss",
                }
            )
    return out
