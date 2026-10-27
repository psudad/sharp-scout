# Football pace model — walk-forward backtest

Shadow-only research model (tempo × opponent-adjusted efficiency). Does not affect live Sharp Scout picks or the public site.

## Data sources

- **NFL:** nflverse schedules + PBP (closing spread/total, finals).
- **NCAAF:** cfbfastR PBP (`spread`, `over_under`, scores); FBS + FCS where lines exist.

**Injury adjustments:** NFL backtest uses nflverse weekly reports; NCAAF has no free historical injury feed. See `docs/football_pace_injury_adjust.md`.

## Tuning methodology

Parameters tuned on **2023–2024** only (`scripts/tune_football_pace.py`): market blend toward close, optional edge caps, and min edges targeting ~10–25% combined play rate. Holdout **2025–2026** reported separately below.

## NFL — tuned vs legacy (walk-forward)

Play rate = (spread picks + total picks) / (2 × games with lines). **Tuned** uses `data/shadow/football_pace/tuning.json` (market blend + selective min edges). **Legacy** = no blend, NFL 2.5 / NCAAF 3.5 pt mins.

Tuned params: `{"market_blend_margin": 0.55, "market_blend_total": 0.35, "max_edge_spread": null, "max_edge_total": null, "min_edge_spread": 8.0, "min_edge_total": 6.0, "in_sample_spread_roi": 9.09, "in_sample_play_rate_pct": 24.72, "score": 9.09, "lean_min_edge_spread": 6.0, "lean_min_edge_total": 4.0}`

### In-sample vs OOS — Unadjusted

| Sample | Model | Games | Spread picks | Spread W-L-P | Spread Win% | Spread ROI | Play rate% | Total picks | Total W-L-P | Total Win% | Total ROI |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| In-sample 2023–2024 legacy | 544 | 401 | 202-188-11 | 51.79% | -1.12% | 79.23% | 461 | 234-224-3 | 51.09% | -2.46% |
| In-sample 2023–2024 tuned | 544 | 0 | 0-0-0 | 0.0% | None% | 22.43% | 244 | 117-127-0 | 47.95% | -8.46% |
| OOS 2025–2026 legacy | 379 | 306 | 142-159-5 | 47.18% | -9.94% | 83.38% | 326 | 157-169-0 | 48.16% | -8.06% |
| OOS 2025–2026 tuned | 379 | 0 | 0-0-0 | 0.0% | None% | 21.64% | 164 | 81-83-0 | 49.39% | -5.71% |

### In-sample vs OOS — Injury-adjusted

| Sample | Model | Games | Spread picks | Spread W-L-P | Spread Win% | Spread ROI | Play rate% | Total picks | Total W-L-P | Total Win% | Total ROI |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| In-sample 2023–2024 legacy | 542 | 405 | 208-186-11 | 52.79% | 0.78% | 79.15% | 453 | 229-220-4 | 51.0% | -2.63% |
| In-sample 2023–2024 tuned | 542 | 0 | 0-0-0 | 0.0% | None% | 21.49% | 233 | 120-112-1 | 51.72% | -1.25% |
| OOS 2025–2026 legacy | 379 | 305 | 146-155-4 | 48.5% | -7.4% | 82.72% | 322 | 159-163-0 | 49.38% | -5.73% |
| OOS 2025–2026 tuned | 379 | 0 | 0-0-0 | 0.0% | None% | 21.77% | 165 | 83-82-0 | 50.3% | -3.97% |

### NFL injury-adjusted spread bucket 5–7 (OOS 2025–2026, tuned blend, min edge 5.0)

| Picks | W-L-P | Win% | ROI @ -110 |
|---:|---:|---:|---:|
| 37 | 24-13-0 | 64.86% | 23.83% |

_Separate holdout check at 5.0 pt spread threshold (production play threshold is 8.0). 7+ bucket on same holdout remains negative._

## NFL pace model backtest

- Seasons: [2023, 2024, 2025, 2026]
- Games graded (with closing lines): 923
- Min edge spread / total: 8.0 / 6.0 pts
- Generated: 2026-10-27T12:20:21.467151+00:00
- Injury history: NFL adjusted grades use nflverse weekly injury reports (Out/Doubtful/Questionable).

### Unadjusted — spread (ATS vs close)

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 0 | 0-0-0 | 0.0% | None% | 0.0% |

### Unadjusted — total (O/U vs close)

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 379 | 185-194-0 | 48.81% | -6.81% | 41.06% |

### Injury-adjusted — spread

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 0 | 0-0-0 | 0.0% | None% | 0.0% |

### Injury-adjusted — total

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 366 | 190-175-1 | 52.05% | -0.62% | 39.74% |

### Unadjusted spread by edge bucket

_No picks in buckets._

### Injury-adjusted spread by edge bucket

_No picks in buckets._


## NCAAF — tuned vs legacy (walk-forward)

Play rate = (spread picks + total picks) / (2 × games with lines). **Tuned** uses `data/shadow/football_pace/tuning.json` (market blend + selective min edges). **Legacy** = no blend, NFL 2.5 / NCAAF 3.5 pt mins.

Tuned params: `{"market_blend_margin": 0.75, "market_blend_total": 0.75, "max_edge_spread": null, "max_edge_total": null, "min_edge_spread": 11.0, "min_edge_total": 11.0, "in_sample_spread_roi": -8.01, "in_sample_play_rate_pct": 23.96, "score": -8.01, "lean_min_edge_spread": 9.0, "lean_min_edge_total": 9.0}`

### In-sample vs OOS — Unadjusted

| Sample | Model | Games | Spread picks | Spread W-L-P | Spread Win% | Spread ROI | Play rate% | Total picks | Total W-L-P | Total Win% | Total ROI |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| In-sample 2023–2024 legacy | 1478 | 1280 | 614-643-23 | 48.85% | -6.75% | 89.14% | 1355 | 672-662-21 | 50.37% | -3.83% |
| In-sample 2023–2024 tuned | 1478 | 0 | 0-0-0 | 0.0% | None% | 0.0% | 0 | 0-0-0 | 0.0% | None% |
| OOS 2025–2026 legacy | 1250 | 1074 | 513-547-14 | 48.4% | -7.61% | 88.56% | 1140 | 563-577-0 | 49.39% | -5.72% |
| OOS 2025–2026 tuned | 1250 | 0 | 0-0-0 | 0.0% | None% | 0.0% | 0 | 0-0-0 | 0.0% | None% |

### In-sample vs OOS — Injury-adjusted

| Sample | Model | Games | Spread picks | Spread W-L-P | Spread Win% | Spread ROI | Play rate% | Total picks | Total W-L-P | Total Win% | Total ROI |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| In-sample 2023–2024 legacy | 0 | 0 | 0-0-0 | 0.0% | None% | 0.0% | 0 | 0-0-0 | 0.0% | None% |
| In-sample 2023–2024 tuned | 0 | 0 | 0-0-0 | 0.0% | None% | 0.0% | 0 | 0-0-0 | 0.0% | None% |
| OOS 2025–2026 legacy | 0 | 0 | 0-0-0 | 0.0% | None% | 0.0% | 0 | 0-0-0 | 0.0% | None% |
| OOS 2025–2026 tuned | 0 | 0 | 0-0-0 | 0.0% | None% | 0.0% | 0 | 0-0-0 | 0.0% | None% |

### NFL injury-adjusted spread bucket 5–7 (OOS 2025–2026, tuned only)

_N/A for NCAAF (no historical injury backtest)._

## NCAAF pace model backtest

- Seasons: [2023, 2024, 2025, 2026]
- Games graded (with closing lines): 2737
- Min edge spread / total: 11.0 / 11.0 pts
- Generated: 2026-10-27T12:26:43.288713+00:00
- Injury history: No free historical NCAAF injury feed; injury-adjusted backtest not run.

### Unadjusted — spread (ATS vs close)

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 0 | 0-0-0 | 0.0% | None% | 0.0% |

### Unadjusted — total (O/U vs close)

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 0 | 0-0-0 | 0.0% | None% | 0.0% |

### Injury-adjusted — spread

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 0 | 0-0-0 | 0.0% | None% | 0.0% |

### Injury-adjusted — total

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 0 | 0-0-0 | 0.0% | None% | 0.0% |

### Unadjusted spread by edge bucket

_No picks in buckets._

### Injury-adjusted spread by edge bucket

_No picks in buckets._


