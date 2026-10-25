# 2026 NFL simulation totals — walk-forward backtest report

Reproduce: `python scripts/run_nfl_totals_season_backtest.py`

## Root cause (sim low bias)

1. **Drive volume:** `drives_per_game` summed recency **weights** per drive instead of counting drives, collapsing every team to the **8.5** floor.
2. **Scoring rate:** Team rates used `nfl_rating_plays`, which drops **field_goal** plays, so points-per-drive was ~**1.42** instead of ~**1.9** (missing made FGs).
3. **Simulator:** Continuous normal “PPD” with ad-hoc TD spikes under-produced relative to discrete TD/FG scoring.

## Mean signed error (sim median − actual)

| | vs final | vs Pinnacle close |
|--|----------|-------------------|
| **Raw sim (before WF bias fix)** | −7.45 | −6.34 |
| **Walk-forward calibrated sim** | −0.77 | +0.34 |

Walk-forward bias = mean(prior `sim_median_raw − final`); applied as `sim_cal = sim_raw − bias` (no full-season fit).

## Headline results (94 games, graded vs Pinnacle close)

| Version | W-L-P | Units @ -110 | Units @ Pinnacle close | MAE vs final |
|--------|-------|--------------|------------------------|--------------|
| **Old model lean** (CSV) | 38-54-2 | -19.45 | -17.94 | 11.50 |
| **Sim-only lean** (calibrated) | 42-50-2 | -11.82 | -10.20 | 11.79 |
| **Blended lean** (WF weight) | 47-45-2 | -2.27 | -0.63 | 10.57 |
| **Market close** (reference) | — | — | — | 10.57 |

**Sim-only by side (close):** Over 22-25-2; Under 20-25-0 (was ~92 Unders before fix).

**Approximate card gate** (sim_p ≥ 50%, EV 4–12% vs **scan-time** `market_total` + `pinnacle_price_at_scan`; no Phase-4/splits): **41** games pass → **17-22-2**, −6.55u @ -110 (same vs scan line).

Artifacts: `reports/nfl_totals_sim_backtest_2026.csv`, `reports/nfl_totals_sim_backtest_2026_summary.json`.
