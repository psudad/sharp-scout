# Football CLV audit (read-only)

Analysis date: 2026-10-24. No football pipeline logic was changed.

## NCAAF (`data/ncaaf_ledger.json`)

| Slice | Plays | With `clv_prob` | Beat close | Avg `clv_prob` |
| --- | ---: | ---: | ---: | ---: |
| All rows | 837 | 822 | 18.9% | -0.0338 |
| `status=quarantined` | 610 | 601 | 15.3% | -0.0430 |
| `filter_passed=false` (non-quarantine) | 220 | 214 | 27.6% | -0.0093 |
| Certified graded (`filter_passed` + W/L/P) | 4 | 4 | 50.0% | +0.0005 |

**Finding:** Headline CLV on the NCAAF ledger is dominated by **quarantined** and **filter-failed** rows (815 of 822 CLV rows have `filter_passed=false`). Those rows still receive closing lines and `clv_prob` via `finalize_closing_lines`, so aggregate summaries look broadly negative (~19% beat close) even though almost none of these plays were ever certified for the public card. Only four graded plays passed filters — too few for a stable CLV read.

## NFL (`data/ledger.json`)

| Slice | Plays | With `clv_prob` | Beat close | Avg `clv_prob` |
| --- | ---: | ---: | ---: | ---: |
| All rows | 111 | 109 | 71.6% | -0.0026 |
| Quarantined | 66 | (included above) | — | — |

NFL shows the same pattern at smaller scale: most CLV-tagged rows are quarantined research/artifact plays, not LOCKED-card plays. Average `clv_prob` is near zero while beat-close rate looks high because many rows are stale pending lines with small positive `clv_prob` but never graded.

## Recommendation (reporting only)

- Publish CLV rollups for **certified** (`filter_passed=true`, non-quarantined) subsets separately from the full ledger.
- Optionally skip CLV finalization for quarantined rows if the goal is card-quality CLV only (would be a deliberate product change — not applied here).
