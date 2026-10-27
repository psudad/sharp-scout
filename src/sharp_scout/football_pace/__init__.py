"""Shadow-only football pace / efficiency score model (NFL + NCAAF).

Mirrors the NBA score-model idea: tempo × opponent-adjusted efficiency → projected
spread/total vs market. Not wired into live picks or the public site.
"""

from sharp_scout.football_pace.config import NCAAF_PACE_CONFIG, NFL_PACE_CONFIG, SportPaceConfig
from sharp_scout.football_pace.engine import PaceEngine

__all__ = [
    "NCAAF_PACE_CONFIG",
    "NFL_PACE_CONFIG",
    "PaceEngine",
    "SportPaceConfig",
]
