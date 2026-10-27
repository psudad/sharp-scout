# NBA Pace-of-Play injury adjustments (display / paper)

The **Score modeling** cards on the NBA test page show stage-3 possession projections with an optional **injury-adjusted** margin and total. Price-edge pick logic is unchanged.

## Data (free)

- **Injuries:** ESPN public injuries feed (same source as `data/paper/nba_injury_lag.json`).
- **Team assignment:** ESPN `teams/{id}/roster?season=2027` (2026–27 season). Player franchise codes never come from memory, stale rate files, or the injury feed alone.
- **Player value:** ESPN by-athlete season stats, keyed by roster display name. Current-season stats first; prior season used only for numeric rates, not team.

## Status weights

| Status | Weight |
|--------|--------|
| Out | 1.00 |
| Doubtful | 0.75 |
| Questionable | 0.50 |
| Day-to-day | 0.45 |
| Probable | 0.25 |
| Available / Active | 0 (return boost if prior scan was Out/Doubtful/Questionable/D2D) |

## Impact formula

1. `bpm_proxy` from season per-minute box stats (see `player_impact.py`).
2. Split into offense (~62%) and defense (~38%) game-point impacts, plus a small pace drag for high-usage starters.
3. Per-player caps (~6 off / ~4.5 def / ~2 pace pts); per-team caps (~12 off / ~9 def).
4. Apply to projected team points: missing offense lowers that team; missing defense raises opponent scoring; pace drag scales both down slightly.

## Paper grading

Frozen pre-tip snapshots grade **both** raw and injury-adjusted edges vs closing consensus (`ats_vs_close` and `ats_vs_close_injury` in `nba_score_model.json` summary).

## Ops

- Full shadow scan (Odds API): still runs at 10:30 AM & 5:30 PM ET; refreshes rates + injuries on live runs.
- **Extra cron:** `nba-injury-refresh.yml` at ~**1 PM ET** and ~**5 PM ET** (two runs to beat Actions delay) — ESPN only, ET game-date slate, re-renders `docs/nba.html` without an Odds API scan.
