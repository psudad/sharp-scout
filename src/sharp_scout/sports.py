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
    # Outcome variance used for P(cover)/P(over). Measured 2024–26 vs closing lines:
    # NFL margin residual sd 12.4 (market) / 13.3 (model); CFB 14.5 / 22. The old sim
    # implied ~8 (NFL) / ~10 (CFB), which is why p_true=0.98 showed up on +26.5 dogs.
    margin_sd: float = 13.5
    total_sd: float = 13.5
    # Market anchoring: p_true = p_fair + k * (p_model - p_fair), where p_fair is the
    # sharp book's no-vig probability shifted to the offered line. k=1 is model-only.
    # Backtest (2026 graded candidates, honest model sd): NCAAF spreads k=0.3 → 28-18,
    # totals k=0.6 → 19-7; model-only was 32-28 / 26-13. NFL has no demonstrated model
    # edge vs the close (48.7% over 546 games) so it leans harder on the market.
    anchor_k_spread: float = 0.3
    anchor_k_total: float = 0.6
    anchor_k_ml: float = 0.3
    # QA: |model_spread - market home line| above this quarantines the play. With
    # anchoring, disagreement is already down-weighted, so CFB gets a wide band.
    spread_model_line_gap: float = 4.0
    # Quant Pick (soft hybrid): hide the lean when the model opposes the sharp line
    # and the spread/total disagreement is at least this many points (not anchor_k).
    hybrid_model_market_gap: float = 4.0


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
    margin_sd=13.5,
    total_sd=13.5,
    anchor_k_spread=0.3,
    anchor_k_total=0.3,
    anchor_k_ml=0.3,
    spread_model_line_gap=4.0,
    hybrid_model_market_gap=4.0,
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
    margin_sd=17.0,
    total_sd=17.0,
    anchor_k_spread=0.3,
    anchor_k_total=0.6,
    anchor_k_ml=0.2,
    spread_model_line_gap=12.0,
    hybrid_model_market_gap=7.0,
)

SPORTS = {"nfl": NFL, "ncaaf": NCAAF}


def get_sport(key: str) -> SportConfig:
    sport = SPORTS.get((key or "nfl").lower())
    if sport is None:
        raise ValueError(f"Unknown sport '{key}'. Use: {', '.join(SPORTS)}")
    return sport
