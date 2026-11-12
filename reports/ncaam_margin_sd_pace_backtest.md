# NCAAM pace-scaled margin SD (shadow)

## Plain English

The live model treats every game’s scoring noise as **~10.5 points** when turning a projected margin into cover probability. That is pace-blind. This shadow lane uses **√(expected possessions)** scaling so faster games get a slightly wider margin distribution. It does **not** change posted picks; it only logs alternate `p_model` / EV next to the live numbers.

## Fitted parameters (train seasons 2008–2016)

- Model: `sd = base × sqrt(expected_poss / 67.0)`
- **base = 10.4810** (SBRO review train 2008–16; shadow uses Barttorvik projected poss)
- ESPN subsample empirical fit (close total pace proxy): **12.0000**
- Train games used: **1139**
- Holdout games used: **2807** (seasons 2017–2021)

## Holdout calibration (ATS vs consensus close, μ=0)

| SD | NLL/game | Brier | pred mean | obs freq |
|---|---:|---:|---:|---:|
| Live `10.5` | 0.8556 | 0.3044 | 0.3726 | 0.4813 |
| Review pace √ (base=10.481) | 0.8542 | 0.3041 | 0.3731 | 0.4813 |
| ESPN subsample pace √ | 0.8154 | 0.2942 | 0.385 | 0.4813 |

**Δ NLL (review pace − live): -0.0014 / game** on holdout (ESPN consensus, n=2807).

### Reliability (holdout) — live sd

| bin | n | pred | obs | gap |
|---|---:|---:|---:|---:|
| 0.0-0.1 | 241 | 0.063 | 0.415 | +0.352 |
| 0.1-0.2 | 348 | 0.154 | 0.477 | +0.323 |
| 0.2-0.3 | 460 | 0.242 | 0.487 | +0.245 |
| 0.3-0.4 | 582 | 0.334 | 0.519 | +0.185 |
| 0.4-0.5 | 454 | 0.435 | 0.5 | +0.065 |
| 0.5-0.6 | 312 | 0.564 | 0.481 | -0.083 |
| 0.6-0.7 | 215 | 0.658 | 0.488 | -0.17 |
| 0.7-0.8 | 119 | 0.758 | 0.378 | -0.38 |
| 0.8-0.9 | 50 | 0.843 | 0.4 | -0.443 |
| 0.9-1.0 | 26 | 0.935 | 0.462 | -0.474 |

### Reliability (holdout) — pace sd

| bin | n | pred | obs | gap |
|---|---:|---:|---:|---:|
| 0.0-0.1 | 138 | 0.064 | 0.391 | +0.327 |
| 0.1-0.2 | 330 | 0.157 | 0.452 | +0.294 |
| 0.2-0.3 | 554 | 0.257 | 0.495 | +0.238 |
| 0.3-0.4 | 609 | 0.352 | 0.517 | +0.165 |
| 0.4-0.5 | 454 | 0.444 | 0.5 | +0.056 |
| 0.5-0.6 | 312 | 0.556 | 0.481 | -0.075 |
| 0.6-0.7 | 218 | 0.64 | 0.482 | -0.158 |
| 0.7-0.8 | 137 | 0.739 | 0.358 | -0.381 |
| 0.8-0.9 | 38 | 0.838 | 0.553 | -0.285 |
| 0.9-1.0 | 17 | 0.93 | 0.412 | -0.518 |

## 2026 season counterfactual (68 official spread/ML stakes)

| | n | W-L | units | Wilson 95% |
|---|---:|---|---:|---|
| **Posted (live SD)** | 68 | 36-32 | +3.47u | 41.2%–64.3% |
| **Would qualify (pace SD)** | 51 | 28-23 | +5.19u | 41.4%–67.7% |

Dropped by pace SD among posted plays: **17**.

Shadow output path: `data/shadow/ncaam_margin_sd_pace.json` (populated on runner candidate evaluation).
