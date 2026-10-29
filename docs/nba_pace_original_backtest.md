# NBA Pace of Play — original vs live backtest (research)

Isolated replay using walk-forward stage-3 engine, pre-tip lines from `data/paper/nba_score_model.json` scans, and ESPN finals for grading. **Does not change live model code or picks.**

## Commits identified (git)

| Role | SHA | Date (author) | Card logic |
|------|-----|---------------|------------|
| **Original (Oct 25–26 winning slates)** | `e45945aa2f01` | 2026-10-25 19:29 UTC | Raw stage-3 margin/total vs consensus; **≥3 pt** gap; highest-gap spread or total wins. No injury layer on picks (#107 merged Oct 27). |
| **Pre–#116 snapshot (injury-adj, no later gates)** | `b913bcb25311` | 2026-10-28 05:42 UTC | Injury-adjusted margin/total vs line; **≥3 pt**; no raw-gap gate; DTD weight **0.45**; no 0.5× injury scale (#116/#117 not yet on main). |

Note: Jason’s **4–1** and **5–1** nights match the **Oct 25–26 ET** official backfill (not Oct 21–24). Those slates predate injury-adjusted Pace (#107).

## Sample coverage

- ESPN completed regular-season games through **2026-10-28** (ET): **68**
- Paper store graded rows in window: **32**
- With pre-tip consensus spread and/or total in repo: **31**
- **Excluded (no stored pre-tip lines):** **37**

## Head-to-head summary (same 31 graded games with lines; multiple plays per game when both markets qualify)

| Model | W–L | Plays | Units @ 1u −110 | Wilson 95% CI |
|-------|-----|-------|-----------------|---------------|
| Original (raw, pre-injury) | 10-14 | 24 | -4.91u | 24.5–61.2% |
| Original (inj-adj @ b913bcb) | 12-15 | 27 | -4.09u | 27.6–62.7% |
| Current live (raw) | 10-14 | 24 | -4.91u | 24.5–61.2% |
| Current live (injury-adj + raw gate) | 10-13 | 23 | -3.91u | 25.6–63.2% |
| 2026-27 totals shadow | 13-13 | 26 | -1.18u | 32.1–67.9% |

### By market (plays taken)

| Model | Spreads W–L | Spreads u | Totals W–L | Totals u |
|-------|-------------|-----------|------------|----------|
| Original (raw, pre-injury) | 4-7 | -3.36 | 6-7 | -1.55 |
| Original (inj-adj @ b913bcb) | 5-7 | -2.45 | 7-8 | -1.64 |
| Current live (raw) | 4-7 | -3.36 | 6-7 | -1.55 |
| Current live (injury-adj + raw gate) | 4-6 | -2.36 | 6-7 | -1.55 |
| 2026-27 totals shadow | 0-0 | +0.00 | 13-13 | -1.18 |

### Gap buckets (injury-adj gap for current; raw gap for original raw)

| Model | 3–5 | 5–8 | 8+ |
|-------|-----|-----|-----|
| Original (raw, pre-injury) | 3-7 | 5-5 | 2-2 |
| Current live (injury-adj + raw gate) | 3-7 | 5-5 | 2-1 |
| 2026-27 totals shadow | 3-1 | 3-3 | 7-9 |

### Totals: Over vs Under (current injury-adj)

- Over: **2-4**, -2.18u
- Under: **4-3**, +0.64u

## Early official slates (replay check)

- **2026-10-25 ET** original raw: **3-3 (6 plays)** (official backfill **4–1**; DET −1.5 was manual sub-threshold)
- **2026-10-26 ET** original raw: **5-1 (6 plays)** (official backfill **5–1**)

## Oct 28 totals (DEN/NOP, LAL/LAC)
- DEN @ NOP Over: original=yes, current_inj=yes
- LAL @ LAC Over: original=yes, current_inj=yes

## Sample-size / break-even caveats

- Break-even at −110 is **52.38%** (shown as **52.4%**).
- Original raw: **41.7%** on **24** plays → Wilson 95% CI **24.5–61.2%** (includes 52.4% — cannot reject luck).
- Original at or below break-even on this sample; early hot streak alone is not evidence of skill.
- Current injury-adj: **10-13**, **-3.91u** on **23** plays — underperforms original raw on same slates in this replay.

## Plain-English verdict

Across **31** games with stored pre-tip lines, mechanical original raw rules produce **10-14 (-4.91u)** on **24** plays — **below break-even** and not separable from noise (Wilson CI spans 52.4%). Oct **26** replays the published **5–1**; Oct **25** is **3-3 (6 plays)** vs official **4–1** because DET was a manual sub-3 pt play. Current injury-adj + raw gate: **10-13 (-3.91u)** on the same universe — slightly fewer losses but still losing. The opening hot streak does **not** hold on the full available 2026-27 sample; it reads as **variance on ~10–12 plays**, not proof the untouched early engine had lasting skill.

Per-play CSV: `data/paper/nba_pace_original_backtest.csv`

