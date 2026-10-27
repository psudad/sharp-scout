"""Shared projection path: model → injuries → market blend."""

from __future__ import annotations

from typing import Any

from sharp_scout.football_pace.injury_context import InjuryBacktestContext
from sharp_scout.football_pace.config import SportPaceConfig
from sharp_scout.football_pace.engine import PaceEngine
from sharp_scout.football_pace.games import PaceGame
from sharp_scout.football_pace.injury_adjust import project_with_injuries
from sharp_scout.football_pace.market_blend import blend_projection


def project_game(
    engine: PaceEngine,
    g: PaceGame,
    cfg: SportPaceConfig,
    *,
    injury_ctx: InjuryBacktestContext | None = None,
    tracker: Any | None = None,
    live_home_inj: list[dict] | None = None,
    live_away_inj: list[dict] | None = None,
    home_roster: list[str] | None = None,
    away_roster: list[str] | None = None,
) -> tuple[dict[str, float], dict[str, float] | None]:
    """Return (blended unadjusted, blended injury-adjusted or None)."""
    raw = engine.project(g.home, g.away)
    blended = blend_projection(
        raw,
        spread_home=g.spread_home,
        total_line=g.total_line,
        params=cfg.blend,
    )
    adj_blended: dict[str, float] | None = None
    if not cfg.injury_adjustment_enabled:
        return blended, None
    home_inj = away_inj = []
    if injury_ctx and injury_ctx.historical_injuries:
        home_inj, away_inj = injury_ctx.injuries_for(g)
    elif live_home_inj is not None:
        home_inj, away_inj = live_home_inj, live_away_inj or []
    tr = tracker or (injury_ctx.tracker if injury_ctx else None)
    if (home_inj or away_inj) and tr is not None:
        adj_raw = project_with_injuries(
            raw,
            home_injuries=home_inj,
            away_injuries=away_inj,
            tracker=tr,
            home_roster=home_roster or (injury_ctx.roster_names(g.home) if injury_ctx else []),
            away_roster=away_roster or (injury_ctx.roster_names(g.away) if injury_ctx else []),
        )
        adj_blended = blend_projection(
            adj_raw,
            spread_home=g.spread_home,
            total_line=g.total_line,
            params=cfg.blend,
        )
    return blended, adj_blended


def signal_label(edge: float | None, min_play: float, min_lean: float) -> str | None:
    if edge is None:
        return None
    ae = abs(edge)
    if ae >= min_play:
        return "play"
    if ae >= min_lean:
        return "lean"
    return None
