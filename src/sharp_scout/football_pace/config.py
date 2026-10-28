"""League defaults, market blend, and selective play thresholds."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sharp_scout.config import DATA_DIR
from sharp_scout.football_pace.market_blend import BlendParams

TUNING_PATH = DATA_DIR / "shadow" / "football_pace" / "tuning.json"


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
    lean_min_edge_spread: float
    lean_min_edge_total: float
    blend: BlendParams
    edge_buckets: tuple[tuple[float, float | None], ...]
    injury_adjustment_enabled: bool = True


def _load_tuning() -> dict:
    if not TUNING_PATH.exists():
        return {}
    try:
        return json.loads(TUNING_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _sport_params(sport: str, defaults: dict) -> dict:
    raw = _load_tuning().get(sport) or {}
    out = dict(defaults)
    out.update({k: v for k, v in raw.items() if v is not None})
    return out


def _cfg(sport: str, **defaults) -> SportPaceConfig:
    p = _sport_params(sport, defaults)
    blend = BlendParams(
        market_blend_margin=float(p["market_blend_margin"]),
        market_blend_total=float(p["market_blend_total"]),
        max_edge_spread=p.get("max_edge_spread"),
        max_edge_total=p.get("max_edge_total"),
    )
    min_sp = float(p["min_edge_spread"])
    min_tot = float(p["min_edge_total"])
    return SportPaceConfig(
        sport=sport,
        league_plays_per_game=float(p["league_plays_per_game"]),
        league_pts_per_play=float(p["league_pts_per_play"]),
        hca_points=float(p["hca_points"]),
        prior_decay_games=float(p["prior_decay_games"]),
        prior_regress_frac=float(p["prior_regress_frac"]),
        recency_half_life_days=float(p["recency_half_life_days"]),
        min_edge_spread=min_sp,
        min_edge_total=min_tot,
        lean_min_edge_spread=float(p.get("lean_min_edge_spread", min_sp - 2.0)),
        lean_min_edge_total=float(p.get("lean_min_edge_total", min_tot - 2.0)),
        blend=blend,
        edge_buckets=((3.0, 5.0), (5.0, 7.0), (7.0, None)),
        injury_adjustment_enabled=True,
    )


NFL_PACE_CONFIG = _cfg(
    "nfl",
    league_plays_per_game=63.0,
    league_pts_per_play=0.58,
    hca_points=1.75,
    prior_decay_games=4.0,
    prior_regress_frac=1.0 / 3.0,
    recency_half_life_days=21.0,
    min_edge_spread=6.0,
    min_edge_total=6.0,
    lean_min_edge_spread=4.0,
    lean_min_edge_total=4.0,
    market_blend_margin=0.45,
    market_blend_total=0.45,
    max_edge_spread=6.0,
    max_edge_total=6.0,
)

NCAAF_PACE_CONFIG = _cfg(
    "ncaaf",
    league_plays_per_game=72.0,
    league_pts_per_play=0.52,
    hca_points=2.75,
    prior_decay_games=6.0,
    prior_regress_frac=1.0 / 3.0,
    recency_half_life_days=14.0,
    min_edge_spread=7.0,
    min_edge_total=7.0,
    lean_min_edge_spread=5.0,
    lean_min_edge_total=5.0,
    market_blend_margin=0.50,
    market_blend_total=0.50,
    max_edge_spread=8.0,
    max_edge_total=8.0,
)
