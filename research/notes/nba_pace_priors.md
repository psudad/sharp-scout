# NBA Pace of Play — preseason priors (2026-27+)

Sharp Scout builds committed team priors in `data/paper/nba_score_model_priors.json` via:

```bash
python scripts/build_nba_score_model_priors.py
```

## Method (no Odds API)

1. **Prior-season team ratings** — Replay ESPN finals through the stage-3 possession ridge model, then `end_season()` with a ⅓ regression toward league average (same as before).
2. **Roster-implied ratings** — For the target season, pull **live ESPN rosters** and **by-athlete stats** (free public endpoints). Each player gets a BPM-like proxy from points/rebounds/assists/usage; team offense/defense/pace priors are **minutes-weighted** aggregates.
3. **Blend** — Default `55%` roster-implied / `45%` regressed prior-season team numbers so priors move with trades and rotation changes without hardcoding rosters.

The live engine still shrinks in-season game updates toward these priors and (early season) toward consensus spreads stored in paper snapshots — never toward live Odds API calls during settlement or replay.

## When to rebuild

Run the builder after the prior season finishes or during preseason when ESPN publishes new season stats. Commit the updated JSON; cloud agents load it through `ensure_score_engine()` / `apply_committed_priors()`.
