"""Ledger score matching helpers (team aliases, kickoff guards, ambiguity checks)."""

from sharp_scout.settlement.score_match import (
    MatchResult,
    build_score_index,
    match_play_to_score,
    normalize_for_settlement,
)

__all__ = [
    "MatchResult",
    "build_score_index",
    "match_play_to_score",
    "normalize_for_settlement",
]
