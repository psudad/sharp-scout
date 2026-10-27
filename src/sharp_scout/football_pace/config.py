"""League defaults and minimum edge thresholds for shadow pace model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SportPaceConfig:
    sport: str  # "nfl" | "ncaaf"
    league_plays_per_game: float
    league_pts_per_play: float
    hca_points: float
    prior_decay_games: float
    prior_regress_frac: float
    recency_half_life_days: float
    min_edge_spread: float
    min_edge_total: float
    edge_buckets: tuple[tuple[float, float | None], ...]
    injury_adjustment_enabled: bool = True


# NFL: tighter lines → slightly lower bar than college.
NFL_PACE_CONFIG = SportPaceConfig(
    sport="nfl",
    league_plays_per_game=63.0,
    league_pts_per_play=0.58,
    hca_points=1.75,
    prior_decay_games=4.0,
    prior_regress_frac=1.0 / 3.0,
    recency_half_life_days=21.0,
    min_edge_spread=2.5,
    min_edge_total=2.5,
    edge_buckets=((3.0, 5.0), (5.0, 7.0), (7.0, None)),
)

# NCAAF: wider market bands; FBS-only games in backtest/project.
NCAAF_PACE_CONFIG = SportPaceConfig(
    sport="ncaaf",
    league_plays_per_game=72.0,
    league_pts_per_play=0.52,
    hca_points=2.75,
    prior_decay_games=6.0,
    prior_regress_frac=1.0 / 3.0,
    recency_half_life_days=14.0,
    min_edge_spread=3.5,
    min_edge_total=3.5,
    edge_buckets=((3.0, 5.0), (5.0, 7.0), (7.0, None)),
)
