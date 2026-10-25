# NBA shadow game-line backtest (2021–22 through 2025–26, closing MGM/Yahoo)

Research only — **not** wired into live NBA or football pipelines.

## Data & methodology

- Closing lines only (SBR 2010-11–2020-21 close; Yahoo BetMGM 2021-22–2024-25 close). Synthetic sharp=close; FanDuel=close with Pinnacle +10c vs retail at same close; FanDuel +1.0pt line penalty. 2025-26 not in Yahoo GitHub CSVs (run script with --fetch-2025-26 to scrape). Props skipped — no free historical player-prop archive.
- Walk-forward: each game uses only its pregame closing snapshot (no future stats).
- **Props:** skipped — no free multi-season historical player-prop closing lines found.

## Every game (best +EV side per market at close)

- **Record:** 9531-8566-218 on 18315 bets
- **Units @ 1u flat (actual close price):** 133.28

## Headline — Picks gate (production `discover_game_line_edges` + long-dog rule)

- **Record:** 8759-7793-218 on 16770 bets
- **Units @ 1u flat:** 209.72

## Possible picks (positive EV, failed qualification)

- **Record:** 1014-1009 (-69.82u)

## By market (Picks)

| Market | N | Record | Units |
|--------|---|--------|-------|
| spreads | 16704 | 8726-7760-218 | 208.7 |
| h2h | 66 | 33-33 | 1.02 |

## Moneyline Picks by price bucket

- **favorite:** 23-16 (6.76u, n=39)
- **short_dog:** 10-17 (-5.74u, n=27)

## Calibration (Picks, p_true bins)

- n=3310 avg_p=0.529 actual_win=0.518
- n=3310 avg_p=0.535 actual_win=0.527
- n=3310 avg_p=0.535 actual_win=0.552
- n=3310 avg_p=0.535 actual_win=0.544
- n=3310 avg_p=0.535 actual_win=0.505
- n=2 avg_p=0.567 actual_win=1.000

## Win rate by edge bucket (Picks)

- EV 2%–4%: n=16549 win=0.529
- EV 6%–8%: n=3 win=0.667

## Spread line error (market baseline)

- MAE of home margin vs closing spread line (Picks subset): **24.372** (n=16704)
- The shadow game-line model has **no independent margin/total simulator**; edge is purely retail-vs-sharp price. Spread 'model error' equals market close error by construction.

## Plain-English verdict

Over 16770 Picks, flat units are positive, but **single-book synthesis may overstate edge** — treat as directional only until multi-book history exists.

## Suggested fixes (proposals only)

1. **Require multi-book historical snapshots** (or paid Odds API history) before trusting CLV/EV backtests — single-book synthesis inflates apparent edge.
2. **Keep long-dog shrink**; backtest ML long-dog bucket separately — if still negative after gate, raise slope or cap ML dogs entirely.
3. **Add a real team-strength or pace layer** for totals/spreads so margin/total error can be measured against the market, not just price mirroring.

