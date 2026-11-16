# Proposal: ingest shadow v1 webhook NBA totals (not implemented)

## Goal

Store, grade, and show **shadow v1** experimental totals (e.g. Nov 15 IND@PHI U224.5) separately from Sharp Scout score-model plays on `nba.html`, without touching the football official card.

## Suggested storage

| Artifact | Path | Purpose |
|----------|------|---------|
| Ledger | `data/shadow/nba_shadow_v1_ledger.json` | Same schema as `data/shadow/nba_ledger.json` rows; `lane: "shadow_webhook"`, `tier: "paper"`, `pipeline: "nba_shadow_v1"`. |
| Latest scan | `data/shadow/nba_shadow_v1_latest.json` | Append-only intake from webhook (raw payload + normalized signals). |
| Health | `data/health/feeds.json` | Feed id `nba_shadow_v1_webhook` with `last_success` on each accepted POST. |

## Ingest path (future)

1. **GitHub Actions** `workflow_dispatch` or small **FastAPI route** on the existing API (`POST /api/nba/shadow-v1`) behind a shared secret; normalize to internal signal shape; call `append_nba_signals` variant that only writes the v1 ledger (never merges into score-model ledger).
2. **Dedupe** with `_logical_play_key` (one side per event/market/line).
3. **Settle** via existing `scripts/settle_nba.py` extended with `--ledger shadow/v1` or a second settle pass on `nba_shadow_v1_ledger.json`.
4. **Site** — `_is_supplemental_shadow_play` already routes `lane=shadow_webhook` to the Paper / shadow section; wire `build_nba_page` to merge graded history from both ledgers for that section only.

## Non-goals

- No Odds API calls from ingest (webhook carries book/line/price).
- No promotion to official NFL/NCAAM/NCAAM cards.