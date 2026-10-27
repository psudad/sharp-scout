# Football pace model — walk-forward backtest

Shadow-only research model (tempo × opponent-adjusted efficiency). Does not affect live Sharp Scout picks or the public site.

## Data sources

- **NFL:** nflverse `games.parquet` (closing spread/total, finals) and play-by-play parquets (tempo and efficiency; garbage-time filtered via win probability).
- **NCAAF:** sportsdataverse cfbfastR play-by-play parquets (`spread`, `over_under`, scores). FBS vs FBS games only. Official schedule parquet URLs currently 404; lines come from PBP.
- **CollegeFootballData.com:** optional; requires a free API key (`COLLEGE_FOOTBALL_DATA_API_KEY`) — not used here because no key is configured in this environment.

**Injury adjustments:** live via ESPN + nflverse rosters; NFL backtest uses nflverse weekly injury reports. See `docs/football_pace_injury_adjust.md`. NCAAF has no free historical injury feed — injury-adjusted backtest columns are empty for college.

## Default minimum edges

| Sport | Spread | Total |
|---|---:|---:|
| NFL | 2.5 pts | 2.5 pts |
| NCAAF | 3.5 pts | 3.5 pts |

Edge buckets in tables: 3–5, 5–7, 7+ points (absolute gap vs closing line).

## NFL pace model backtest

- Seasons: [2023, 2024, 2025, 2026]
- Games graded (with closing lines): 923
- Min edge spread / total: 2.5 / 2.5 pts
- Generated: 2026-10-27T11:52:05.559812+00:00
- Injury history: NFL adjusted grades use nflverse weekly injury reports (Out/Doubtful/Questionable).

### Unadjusted — spread (ATS vs close)

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 702 | 347-339-16 | 50.58% | -3.43% | 76.06% |

### Unadjusted — total (O/U vs close)

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 772 | 384-385-3 | 49.93% | -4.67% | 83.64% |

### Injury-adjusted — spread

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 700 | 352-333-15 | 51.39% | -1.9% | 76.0% |

### Injury-adjusted — total

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 767 | 383-380-4 | 50.2% | -4.17% | 83.28% |

### Unadjusted spread by edge bucket

| Bucket | Picks | W-L-P | Win% | ROI @ -110 |
|---|---:|---:|---:|---:|
| 3-5 | 158 | 81-70-7 | 53.64% | 2.41% |
| 5-7 | 99 | 49-48-2 | 50.52% | -3.56% |
| 7+ | 391 | 186-200-5 | 48.19% | -8.01% |
| below_3 | 54 | 31-21-2 | 59.62% | 13.81% |

### Injury-adjusted spread by edge bucket

| Bucket | Picks | W-L-P | Win% | ROI @ -110 |
|---|---:|---:|---:|---:|
| 3-5 | 149 | 75-68-6 | 52.45% | 0.13% |
| 5-7 | 112 | 65-45-2 | 59.09% | 12.81% |
| 7+ | 394 | 188-200-6 | 48.45% | -7.5% |
| below_3 | 45 | 24-20-1 | 54.55% | 4.13% |


## NCAAF pace model backtest

- Seasons: [2023, 2024, 2025, 2026]
- Games graded (with closing lines): 2737
- Min edge spread / total: 3.5 / 3.5 pts
- Generated: 2026-10-27T11:54:10.089067+00:00
- Injury history: No free historical NCAAF injury feed; injury-adjusted backtest not run.

### Unadjusted — spread (ATS vs close)

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 2375 | 1147-1191-37 | 49.06% | -6.34% | 86.77% |

### Unadjusted — total (O/U vs close)

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 2512 | 1241-1250-21 | 49.82% | -4.89% | 91.78% |

### Injury-adjusted — spread

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 0 | 0-0-0 | 0.0% | None% | 0.0% |

### Injury-adjusted — total

| Picks | W-L-P | Win% | ROI @ -110 | Clear rate |
|---:|---:|---:|---:|---:|
| 0 | 0-0-0 | 0.0% | None% | 0.0% |

### Unadjusted spread by edge bucket

| Bucket | Picks | W-L-P | Win% | ROI @ -110 |
|---|---:|---:|---:|---:|
| 3-5 | 148 | 66-77-5 | 46.15% | -11.89% |
| 5-7 | 200 | 88-110-2 | 44.44% | -15.15% |
| 7+ | 2027 | 993-1004-30 | 49.72% | -5.07% |

### Injury-adjusted spread by edge bucket

_No picks in buckets._


