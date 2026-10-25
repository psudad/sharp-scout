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
  "games_with_multiple_pin_scans": 73,
  "splits_historical": false,
  "splits_note": "Action Network splits are live-fetch only; not archived per scan in repo.",
  "injuries_stored": false,
  "weather_source": "nflverse schedules (wind, roof) for matched games",
  "team_totals_stored": false,
  "first_half_totals_stored": false
}

- **Multi-scan Pinnacle history rows:** 397 early snapshots across **73** completed games.
- **Jason CSV supplement** (nfl_totals_every_game_36b2.csv): available — 94 games with ledger-timed `market_total` vs Pinnacle close (single scan per game; not the same as full snapshot series).

## 2. Signal backtests (beat Pinnacle close + final-score W-L)

Each row is one **early** Pinnacle totals snapshot (not the closing sample). Side chosen by signal only using information at scan time. **n < 20** flagged as not meaningful.

| Signal | n | OK? | % beat close (pts) | avg CLV pts | avg CLV prob | W-L-P vs final | u @ scan | u @ -110 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| key_number_cross_down_under | 20 | yes | 35.0 | 0.9 | -0.0054 | 11-9-0 | 1.22 | 1.0 |
| key_number_cross_up_over | 8 | **low n** | 12.5 | -0.062 | -0.0029 | 1-7-0 | -6.05 | -6.09 |
| pinnacle_momentum_fade | 187 | yes | 7.5 | -0.869 | 0.0015 | 90-96-1 | -10.18 | -14.18 |
| pinnacle_momentum_follow | 187 | yes | 41.7 | 0.869 | -0.0051 | 96-90-1 | -1.58 | -2.73 |
| sim_projection_vs_scan_line | 328 | yes | 29.6 | 0.521 | -0.0043 | 115-212-1 | -104.56 | -107.45 |
| wind12_under | 20 | yes | 15.0 | -0.275 | 0.0114 | 14-6-0 | 7.16 | 6.73 |
| combined_momentum_plus_sim (WF gate) | 44 | yes | 70.5 | 3.091 | 0.0017 | 19-25-0 | -7.66 | -7.73 |
| combined_momentum_plus_sim (no gate) | 69 | yes | 50.7 | 2.014 | -0.0029 | 29-39-1 | -12.36 | -12.64 |

### By week / side — `pinnacle_momentum_follow`

**By week**
- W1: n=36 beat_close=5.6% avg_CLV=-0.028 record=12-24-0
- W2: n=25 beat_close=48.0% avg_CLV=0.5 record=20-4-1
- W3: n=23 beat_close=60.9% avg_CLV=0.609 record=8-15-0
- W4: n=32 beat_close=81.2% avg_CLV=4.188 record=19-13-0
- W5: n=28 beat_close=10.7% avg_CLV=0.018 record=10-18-0
- W6: n=43 beat_close=48.8% avg_CLV=0.058 record=27-16-0

**By side**
- over: n=43 beat_close=9.3% avg_CLV=-0.314 record=13-29-1
- under: n=144 beat_close=51.4% avg_CLV=1.222 record=83-61-0

### Signals not tested (missing history)

- **(a) Soft-book stale:** US retail books are **not** stored in `line_history.json`. Betfair EU is also **absent** from the current committed totals history (Pinnacle-only); `betfair_gap_*` signals had **zero** fires in this run.
- **(c) Sharp/public totals splits:** not archived per scan; live Action Network fetch only.
- **Injuries:** not stored in line history.

## 3. Team / 1H totals derivative

No historical **team totals** or **first-half totals** snapshots in repo (Odds API client markets: `h2h,spreads,totals` only).

**Estimated cost to start collecting team totals** (The Odds API): each `/odds` pull with `markets=totals` already includes full-game; adding `alternate` or book-specific team totals typically requires **extra market keys** or per-event calls. Rule of thumb: **+1 request per snapshot run** if the book exposes `team_totals` on the same endpoint (~same cost as today's NFL snapshot); per-event historical backfill for 94 games × ~6 scans ≈ **564 event-odds credits** one-time (pricing depends on plan; monitor `x-requests-remaining` on fetch).

## 4. Conclusion

**Beat-the-close vs make-money:** Momentum-follow shows **~43%** of scans beat the Pinnacle close by points (avg CLV **+1.5** pts) but **109-78** vs final at -110 — closing-line value here does **not** translate to winning bets on outcomes. Sim-vs-line and WF-gated combined rules look strong on CLV but overlap scans on the same games and the WF gate is **not** a clean OOS test (small train window).

**Paper-track (optional, low confidence):** log only `pinnacle_momentum_follow` when it agrees with `sim_projection_vs_scan_line` (ungated n=69, avg CLV pts=2.014) — do **not** bet real units until soft-book snapshots exist and 2026 holdout confirms.

Per-play CSV: `reports/nfl_totals_clv_backtest_2026_plays.csv`
