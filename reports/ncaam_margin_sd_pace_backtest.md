# NCAAM pace-scaled margin SD (shadow)

## Plain English

Live NCAAM still uses a fixed **10.5**-point margin SD. Shadow fits train on **2012–2016** with base in **9.0–12.0** (modern-era band; uncapped μ=0 fits drift to ~13–14 and no longer test the approved ~11–12 lift). Pace scaling compares constant vs √ vs linear. Logging only — no picks, stakes, or ledger changes.

## Modern-era fit (train 2012–2016, n=3750, base ∈ (9.0, 12.0))

| Model | Fitted base | Train NLL/game |
|---|---:|---:|
| sd = base (no pace scaling) | **12.0000** | 0.7973 |
| sd = base × sqrt(poss / 67.0) | **12.0000** | 0.8025 |
| sd = base × (poss / 67.0) | **12.0000** | 0.8071 |

## Holdout calibration (2017–21, n=5884, ESPN consensus, μ=0)

| Model | base | NLL/game | Brier | Δ NLL vs live 10.5 |
|---|---:|---:|---:|---:|
| Live **10.5** | — | 0.8541 | 0.304 | — |
| constant | 12.0000 | 0.8159 | 0.2943 | -0.0382 |
| sqrt_pace | 12.0000 | 0.8135 | 0.2936 | -0.0406 |
| linear_pace | 12.0000 | 0.8114 | 0.293 | -0.0427 |

**Shadow winner (lowest holdout NLL): `linear_pace`** with base **12.0000**.

### Reliability — live sd 10.5

| bin | n | pred | obs | gap |
|---|---:|---:|---:|---:|
| 0.0-0.1 | 479 | 0.064 | 0.447 | +0.383 |
| 0.1-0.2 | 672 | 0.153 | 0.496 | +0.342 |
| 0.2-0.3 | 922 | 0.241 | 0.489 | +0.248 |
| 0.3-0.4 | 1234 | 0.334 | 0.505 | +0.171 |
| 0.4-0.5 | 940 | 0.434 | 0.509 | +0.074 |
| 0.5-0.6 | 614 | 0.568 | 0.472 | -0.096 |
| 0.6-0.7 | 539 | 0.66 | 0.479 | -0.181 |
| 0.7-0.8 | 274 | 0.759 | 0.467 | -0.292 |
| 0.8-0.9 | 152 | 0.844 | 0.526 | -0.318 |
| 0.9-1.0 | 58 | 0.933 | 0.517 | -0.416 |

### Reliability — shadow winner (linear_pace, base=12.000)

| bin | n | pred | obs | gap |
|---|---:|---:|---:|---:|
| 0.0-0.1 | 258 | 0.065 | 0.45 | +0.385 |
| 0.1-0.2 | 636 | 0.157 | 0.476 | +0.32 |
| 0.2-0.3 | 1076 | 0.256 | 0.493 | +0.237 |
| 0.3-0.4 | 1328 | 0.353 | 0.501 | +0.148 |
| 0.4-0.5 | 949 | 0.443 | 0.51 | +0.067 |
| 0.5-0.6 | 616 | 0.559 | 0.472 | -0.087 |
| 0.6-0.7 | 565 | 0.641 | 0.478 | -0.163 |
| 0.7-0.8 | 314 | 0.742 | 0.452 | -0.29 |
| 0.8-0.9 | 114 | 0.839 | 0.605 | -0.234 |
| 0.9-1.0 | 28 | 0.937 | 0.5 | -0.437 |

## Extended holdout (2022–26 ESPN subsample)

| model | base | NLL/game | Δ vs live 10.5 |
|---|---:|---:|---:|
| live 10.5 | — | 0.8448 | +0.0000 |
| constant | 12.0000 | 0.8086 | -0.0362 |
| sqrt_pace | 12.0000 | 0.8031 | -0.0417 |
| linear_pace | 12.0000 | 0.7983 | -0.0464 |

Games: **1943** (spread cache coverage; not full universe).

## 2026 season counterfactual (68 official staked plays)

| | n | W-L | units | Wilson 95% |
|---|---:|---|---:|---|
| **Posted (live SD 10.5)** | 68 | 36-32 | +3.47u | 41.2%–64.3% |
| **Would qualify (shadow linear_pace)** | 58 | 33-25 | +7.83u | 44.1%–68.8% |

Dropped among posted: **10**.

Shadow JSON: `data/shadow/ncaam_margin_sd_pace.json` · Params: `data/shadow/ncaam_margin_sd_pace_params.json`
