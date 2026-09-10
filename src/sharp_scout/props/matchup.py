"""Opponent defensive context for player-prop projections."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sharp_scout.phase1.ratings import TeamPower


def opponent_matchup_tilts(
    ratings: dict[str, TeamPower] | None,
    opponent: str,
) -> tuple[float, float]:
    """Pass- and rush-funnel inputs for ``apply_matchup``.

    Returns EPA/YPP-style deltas relative to league average. Positive pass input means
    the opponent allows more passing production than average; positive rush input means
    a softer run defense.
    """
    if not ratings or opponent not in ratings:
        return 0.0, 0.0
    league_def_epa = float(np.mean([r.def_epa for r in ratings.values()]))
    league_def_ypp = float(np.mean([r.def_ypp for r in ratings.values()]))
    opp = ratings[opponent]
    # ``def_epa`` / ``def_ypp`` are higher when the defense is *better*, so flip the sign
    # to express how much the opponent *allows* relative to average.
    pass_allowed = league_def_epa - opp.def_epa
    rush_allowed = league_def_ypp - opp.def_ypp
    return pass_allowed, rush_allowed
