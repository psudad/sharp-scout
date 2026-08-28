"""Sport registry — NFL and NCAAF share the same 4-phase engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SportConfig:
    key: str
    display: str
    odds_sport_key: str
    action_league: str
    action_referer: str
    artifact_name: str
    ledger_name: str
    pbp_cache_prefix: str
    base_hfa: float
    scoring_base: float  # typical PPG environment
    epa_scale: float


NFL = SportConfig(
    key="nfl",
    display="NFL",
    odds_sport_key="americanfootball_nfl",
    action_league="nfl",
    action_referer="https://www.actionnetwork.com/nfl/public-betting",
    artifact_name="latest_signals.json",
    ledger_name="ledger.json",
    pbp_cache_prefix="pbp",
    base_hfa=2.2,
    scoring_base=22.5,
    epa_scale=28.0,
)

NCAAF = SportConfig(
    key="ncaaf",
    display="NCAA Football",
    odds_sport_key="americanfootball_ncaaf",
    action_league="ncaaf",
    action_referer="https://www.actionnetwork.com/ncaaf/public-betting",
    artifact_name="latest_ncaaf_signals.json",
    ledger_name="ncaaf_ledger.json",
    pbp_cache_prefix="cfb_pbp",
    base_hfa=3.0,  # college HFA is typically larger
    scoring_base=27.5,
    epa_scale=26.0,
)

SPORTS = {"nfl": NFL, "ncaaf": NCAAF}


def get_sport(key: str) -> SportConfig:
    sport = SPORTS.get((key or "nfl").lower())
    if sport is None:
        raise ValueError(f"Unknown sport '{key}'. Use: {', '.join(SPORTS)}")
    return sport
