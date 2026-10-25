# 2026 NFL totals — early line / CLV research

Research only (PR). Reproduce: `python scripts/run_nfl_totals_clv_backtest.py`.

## 1. Data coverage (honest)

{
  "line_history_path": "data/line_history.json",
  "snapshot_books_in_totals_history": {
    "pinnacle": 9014
  },
  "sharp_only_recording": true,
  "soft_retail_books_stored": false,
  "note_soft_books": "record_snapshot() uses sharp_only=True; US retail books are not in line_history. Committed totals history on main is Pinnacle-only (no Betfair/retail series).",
  "completed_nfl_games_2026": 94,
  "games_with_event_id_match": 91,
  "games_with_multiple_pin_scans": 71,
  "splits_historical": false,
  "splits_note": "Action Network splits are live-fetch only; not archived per scan in repo.",
  "injuries_stored": false,
  "weather_source": "nflverse schedules (wind, roof) for matched games",
  "team_totals_stored": false,
  "first_half_totals_stored": false
}

- **Multi-scan Pinnacle history rows:** 381 early snapshots across **71** completed games.
- **Jason CSV supplement** (nfl_totals_every_game_36b2.csv): available — 94 games with ledger-timed `market_total` vs Pinnacle close (single scan per game; not the same as full snapshot series).

## 2. Signal backtests (beat Pinnacle close + final-score W-L)

Each row is one **early** Pinnacle totals snapshot (not the closing sample). Side chosen by signal only using information at scan time. **n < 20** flagged as not meaningful.

| Signal | n | OK? | % beat close (pts) | avg CLV pts | avg CLV prob | W-L-P vs final | u @ scan | u @ -110 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| key_number_cross_down_under | 23 | yes | 34.8 | -0.043 | 0.0005 | 14-9-0 | 4.01 | 3.73 |
| key_number_cross_up_over | 8 | **low n** | 0.0 | -0.188 | -0.0029 | 2-6-0 | -4.06 | -4.18 |
| pinnacle_momentum_fade | 182 | yes | 8.8 | -0.588 | -0.0028 | 83-98-1 | -19.86 | -22.55 |
| pinnacle_momentum_follow | 182 | yes | 40.7 | 0.588 | -0.0014 | 98-83-1 | 7.45 | 6.09 |
| sim_projection_vs_scan_line | 314 | yes | 28.3 | 0.295 | -0.0045 | 112-201-1 | -96.86 | -99.18 |
| wind12_under | 15 | **low n** | 20.0 | 0.1 | 0.0114 | 9-6-0 | 2.43 | 2.18 |
| combined_momentum_plus_sim (WF gate) | 35 | yes | 62.9 | 2.114 | 0.005 | 16-19-0 | -4.48 | -4.45 |
| combined_momentum_plus_sim (no gate) | 60 | yes | 43.3 | 1.283 | -0.0017 | 26-33-1 | -9.18 | -9.36 |

### By week / side — `pinnacle_momentum_follow`

**By week**
- W1: n=36 beat_close=5.6% avg_CLV=-0.028 record=12-24-0
- W2: n=25 beat_close=48.0% avg_CLV=0.5 record=20-4-1
- W3: n=20 beat_close=55.0% avg_CLV=0.55 record=8-12-0
- W4: n=25 beat_close=76.0% avg_CLV=3.0 record=19-6-0
- W5: n=23 beat_close=4.3% avg_CLV=-0.065 record=10-13-0
- W6: n=52 beat_close=55.8% avg_CLV=0.212 record=28-24-0
- W7: n=1 beat_close=0.0% avg_CLV=0.0 record=1-0-0

**By side**
- over: n=39 beat_close=0.0% avg_CLV=-0.103 record=13-25-1
- under: n=143 beat_close=51.7% avg_CLV=0.776 record=85-58-0

### Signals not tested (missing history)

- **(a) Soft-book stale:** US retail books are **not** stored in `line_history.json`. Betfair EU is also **absent** from the current committed totals history (Pinnacle-only); `betfair_gap_*` signals had **zero** fires in this run.
- **(c) Sharp/public totals splits:** not archived per scan; live Action Network fetch only.
- **Injuries:** not stored in line history.

## 3. Team / 1H totals derivative

No historical **team totals** or **first-half totals** snapshots in repo (Odds API client markets: `h2h,spreads,totals` only).

**Estimated cost to start collecting team totals** (The Odds API): each `/odds` pull with `markets=totals` already includes full-game; adding `alternate` or book-specific team totals typically requires **extra market keys** or per-event calls. Rule of thumb: **+1 request per snapshot run** if the book exposes `team_totals` on the same endpoint (~same cost as today's NFL snapshot); per-event historical backfill for 94 games × ~6 scans ≈ **564 event-odds credits** one-time (pricing depends on plan; monitor `x-requests-remaining` on fetch).

## 4. Conclusion

**Beat-the-close vs make-money:** Momentum-follow shows **40.7%** of scans beat the Pinnacle close by points (avg CLV **0.588** pts) with record **98-83-1** vs final — modest CLV on ~40% of scans does not imply profitable outcome bets. Combined rules overlap scans on the same games; the WF gate is a weak OOS filter (small train window).

**Paper-track (optional, low confidence):** log only `pinnacle_momentum_follow` when it agrees with `sim_projection_vs_scan_line` (ungated n=60, avg CLV pts=1.283) — do **not** bet real units until soft-book snapshots exist and 2026 holdout confirms.

Per-play CSV: `reports/nfl_totals_clv_backtest_2026_plays.csv`
