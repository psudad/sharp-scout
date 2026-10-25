# Multi-book line snapshots + paper momentum tracker

## Odds API credit impact

**Zero additional credits.** `OddsClient.fetch_odds()` already requests `regions=us,us2,eu` and `markets=h2h,spreads,totals` once per pipeline / pregame / `record_line_snapshots.py` run. Normalized events already include every bookmaker returned (Pinnacle, Betfair EU, DraftKings, FanDuel, etc.). This change only **persists more of the same JSON** into `data/line_history.json` (spreads + totals for all books; h2h remains sharp-only to limit size).

## Storage approach

| Mechanism | Detail |
|-----------|--------|
| **Deduping** | Unchanged: append only when `(line, price)` changes for that book |
| **Markets** | All books: `spreads`, `totals`; sharp books only: `h2h` |
| **Archive** | Samples with `ts` before `line_history_retain_after` (default `2026-06-01`) move to `data/line_history_archive.json` on save |
| **Demo filter** | `demo-kc-buf` never written to line history on live runs |
| **Steam / CLV** | Steam still counts **sharp books only**; CLV closing line still prefers Pinnacle |

## Paper tracker (NFL totals)

- **File:** `data/paper/nfl_totals_momentum_follow.json` (paper-only; not ledger/card)
- **Rule:** First scan per game where Pinnacle total moved **≥ 0.5** pts from earliest recorded Pinnacle open → bet **with** the move (up = Over, down = Under) at scan line/price
- **Grading:** `settle_plays.py` (NFL) fills Pinnacle close from `line_history`, final from scores
- **Hook:** After each live `record_snapshot` in NFL pipeline

## Demo KC@BUF board fix

**Cause:** `mock_odds_events()` (`demo-kc-buf`) was upserted into `nfl_game_totals.json` when the pipeline used demo odds or **fell back to mock after a failed live fetch**, with `commence_time=now()` (explains 08:41 ET kickoff on Oct 25 while KC plays @ SEA tonight).

**Fix:** `upsert_totals_rows(..., allow_demo_events=False)` by default + `purge_demo_games()` on each upsert; demo snapshots skipped in line history unless `--demo`.
