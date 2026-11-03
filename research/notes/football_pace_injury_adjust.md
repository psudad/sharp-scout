# Football pace model — injury adjustment (shadow)

Mirrors the NBA score-model injury layer: **unadjusted** pace × efficiency projections sit beside **injury-adjusted** lines using free availability feeds and current-season usage.

## Live (before kickoff)

| Sport | Availability | Roster / depth |
|------|----------------|----------------|
| NFL | ESPN injuries + official-style statuses (Out, Doubtful, Questionable, IR) | ESPN team roster (position + depth order) + nflverse `players.parquet` for position |
| NCAAF | ESPN injuries (partial team coverage) | Usage from cfbfastR PBP; no reliable free depth chart API |

Commands:

```bash
source .venv/bin/activate
python scripts/run_football_pace_project.py --sport both --season 2025 --week 9 --save
```

Each game in the JSON output includes `unadjusted` and `injury_adjusted` blocks (points, margin, total, edges, picks) plus injury lists on the adjusted side.

## Point impact formula

For each listed player on the **current roster** with a non-active status:

1. **Status weight** — Out / IR / Inactive = 100%; Doubtful ≈ 72%; Questionable ≈ 38%; Probable ≈ 12%.
2. **Offense** — `status_weight × position_cap × touch_share` (from season-to-date PBP touches: pass / rush / target).
3. **Defense** — `status_weight × position_cap × depth_factor` (CB/EDGE/LB/S tiers; starter depth rank from ESPN roster when available).

Caps (single-player max, before share): QB ≈ 5.5 pts offense; WR ≈ 3.2; EDGE ≈ 3.0 defense; etc. See `football_pace/player_value.py`.

Applied to the base projection:

- Own offensive injuries **lower** your expected points.
- Opponent **defensive** injuries **raise** your expected points (weaker defense faced).
- Home-field split is unchanged; totals move with offensive/defensive point shifts.

## Backtest

| Sport | Injury-adjusted backtest |
|-------|-------------------------|
| NFL | Yes — nflverse weekly injury parquets (`report_status` Out/Doubtful/Questionable), walk-forward with PBP touch shares |
| NCAAF | **No historical feed** — backtest reports **unadjusted** only for injury-adjusted columns (null / empty); live slate still uses ESPN when present |

```bash
python scripts/run_football_pace_backtest.py --sport both --seasons 2023 2024 2025 2026
```

Report: `docs/football_pace_backtest.md` (unadjusted + injury-adjusted tables for NFL).

## Extension hooks

- Plug richer defensive snap counts or official participation when available in `PlayerValueTracker.observe_game_touches`.
- NCAAF: CollegeFootballData.com injury endpoint if `COLLEGE_FOOTBALL_DATA_API_KEY` is set (not required for v1).
