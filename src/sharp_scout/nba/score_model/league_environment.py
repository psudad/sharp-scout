"""Walk-forward league scoring environment (efficiency re-centering)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sharp_scout.config import get_settings
from sharp_scout.nba.score_model.engine import LEAGUE_ORTG
from sharp_scout.nba.score_model.state import _season_label

if TYPE_CHECKING:
    from sharp_scout.nba.score_model.engine import V2Engine


def correction_enabled() -> bool:
    return bool(getattr(get_settings(), "nba_league_efficiency_correction_enabled", False))


def rolling_league_ortg(
    engine: V2Engine,
    *,
    before: datetime,
    min_games: int | None = None,
) -> float | None:
    """Mean ORtg across teams from finals strictly before ``before`` in the same NBA season."""
    settings = get_settings()
    need = min_games if min_games is not None else int(
        getattr(settings, "nba_league_efficiency_min_games", 30)
    )
    season = _season_label(before)
    rows = [r for r in engine.history if r.date < before and _season_label(r.date) == season]
    if len(rows) < need:
        return None
    vals = [(float(r.home_ortg) + float(r.away_ortg)) / 2.0 for r in rows]
    return sum(vals) / len(vals)


def efficiency_scale(engine: V2Engine, game_date: datetime) -> float | None:
    """Multiplicative scale for off/def ratings; None when disabled or sample too small."""
    if not correction_enabled():
        return None
    settings = get_settings()
    mu = rolling_league_ortg(engine, before=game_date)
    if mu is None:
        return None
    anchor = float(getattr(settings, "nba_league_efficiency_anchor_ortg", LEAGUE_ORTG))
    if anchor <= 0:
        return None
    return mu / anchor
