# NCAAF totals high-EV shadow ledger

Private paper track for **totals** with model EV at or above the LOCKED card ceiling (12%).
Runs inside the existing NCAAF pipeline (`record_from_pipeline` on in-memory signals).

## Odds API credits

**Zero additional credits per run.** Shadow capture reads the same `all_signals` list
already built by `run_ncaaf_pipeline`; it does not call The Odds API or Action Network again.

## Artifacts

| Path | Purpose |
|------|---------|
| `data/shadow/ncaaf_totals_high_ev_ledger.json` | One row per game/side/bucket (deduped) |
| `data/shadow/ncaaf_totals_high_ev_summary.json` | Record, units, ROI, avg CLV by bucket |
| `reports/ncaaf_totals_high_ev.md` | Human-readable summary (not on GitHub Pages) |

## Buckets

- `ev_12_16` — 12% ≤ EV < 16%
- `ev_16_plus` — EV ≥ 16%
- `cert_miss_4_12` — 4–12% EV, Phase 4 passed, failed product gate on confirmation/p_fair only

Settlement: `settle_shadow_ledger()` (wired into `settle_plays.py` / `settle_now.py` for NCAAF).
CLV uses shared `data/line_history.json` closing snapshots.
