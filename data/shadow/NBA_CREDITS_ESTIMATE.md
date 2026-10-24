# NBA shadow — Odds API credit estimate

Plan: Jason’s **$59/mo (~100k credits)** tier shared with NFL/NCAAF.

## Per run (`scripts/run_nba_shadow.py`)

| Step | Credits (typical) |
| --- | ---: |
| `GET /sports/basketball_nba/odds` (game lines, all books) | 1 |
| Player props (`GET .../events/{id}/odds`) | 1 × **N** events |

Defaults (`config.py`): `nba_max_prop_events_per_run=6`, `nba_prop_horizon_hours=36`.

**Typical shadow run:** 1 + 6 = **7 credits**.

## Scheduled shadow workflow

Proposed: **2 runs/day** during the paper window (Nov 2 – Dec 13, 2026) ≈ 14 credits/day → **~420 credits/month** for NBA shadow alone, leaving ample headroom for football pipelines if prop event cap stays at 6.

## Pinnacle NBA props probe (2026-10-24)

One live probe on `player_points` for a Hornets @ Heat event:

- **11** US/EU books returned.
- **`pinnacle_present`: false** on that event/market (Pinnacle did not appear in the feed).
- Game-line fetches still include Pinnacle in `eu` region; props fall back to **multi-book no-vig consensus** per the agreed strategy.

Re-run without burning extra credits:

```bash
python scripts/probe_nba_pinnacle_props.py --markets player_points
```

Use `--event-id` to target a specific game; keep `--markets` to a single market during quota-sensitive periods.
