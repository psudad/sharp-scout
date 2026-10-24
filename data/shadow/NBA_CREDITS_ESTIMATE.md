# NBA shadow — Odds API credit estimate

Plan: Jason’s **$59/mo (~100k credits)** tier shared with NFL/NCAAF.

## Per run (`scripts/run_nba_shadow.py`)

| Step | Credits (typical) |
| --- | ---: |
| `GET /sports/basketball_nba/odds` (game lines, `regions=us,us2,eu`) | **~9** |
| Player props per game (`GET .../events/{id}/odds`, `regions=us,us2`) | **~10** each |

Prop cost assumes **5 markets × 2 regions** (`nba_prop_market_list` length × `nba_prop_regions`).

Defaults (`config.py`): `nba_max_prop_events_per_run=10`, `nba_prop_horizon_hours=36`, `nba_prop_regions=us,us2`.

**Typical shadow run (max budget):** ~9 + (10 × 10) ≈ **~100 credits** per run when all prop-event slots fill.

## Scheduled shadow workflow

Proposed: **2 runs/day** during the paper window (Nov 2 – Dec 13, 2026) ≈ **~200 credits/day** at the cap above → plan quota accordingly alongside football pipelines.

## Pinnacle NBA props probe (2026-10-24)

One live probe on `player_points` for a Hornets @ Heat event:

- **11** US/EU books returned.
- **`pinnacle_present`: false** on that event/market (Pinnacle did not appear in the feed).
- Game-line fetches still include Pinnacle in `eu` region; props use **`us,us2` only** and fall back to **multi-book no-vig consensus**.

Re-run without burning extra credits:

```bash
python scripts/probe_nba_pinnacle_props.py --markets player_points
```

Use `--event-id` to target a specific game; keep `--markets` to a single market during quota-sensitive periods.
