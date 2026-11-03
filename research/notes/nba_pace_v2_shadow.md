# Pace of Play v2 shadow (paper only)

Production **v1** is the official Jason card: committed priors on `nba_score_model_priors.json`, the live score engine in `nba_score_model_state.json`, a **3.0 pt** injury-adjusted gap, and the same qualification rules as `main`.

**v2** runs in parallel on every NBA paper scan as `shadow_v2` (separate engine state + `nba_score_model_priors_v2.json`). It is shown on `docs/nba.html` only in the labeled shadow comparison block — never mixed into official plays.

## Promotion rule (no retuning on one night)

v2 may replace v1 only after:

1. **~100 shadow plays** logged with stored pre-tip lines (no look-ahead priors).
2. v2 **beats v1 on CLV** (line moved toward the model vs last pre-tip consensus) over that sample, with W/L and model error vs close reported alongside.

Do not change v2 toggles or thresholds in reaction to a single slate.

## Config toggles (v2 only)

See `Settings` in `config.py`: `nba_pace_v2_shadow_enabled`, `nba_v2_early_min_gap`, `nba_v2_market_blend`, `nba_v2_schedule_context`, `nba_v2_roster_priors`, `nba_v2_require_raw_gap`, `nba_v2_exclude_large_gap_early`, etc.

## Optional pre-tip snapshot (disabled)

`nba_pace_pre_tip_snapshot_enabled=false` by default (Odds API credits). When enabled later, `nba_pace_pre_tip_snapshot_minutes` (default 15) documents the intended extra line capture inside the existing scan plan — no new API product.
