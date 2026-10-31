# NBA Pace of Play — original vs live backtest (research)

Isolated replay using walk-forward stage-3 engine. Lines: **repo** pre-tip Odds API scans (`data/paper/nba_score_model.json`) plus **ESPN pickcenter backfill** (`data/paper/nba_espn_pregame_lines.json`, backtest-only). **Does not change live model code or picks.**

## Commits identified (git)

| Role | SHA | Date (author) | Card logic |
|------|-----|---------------|------------|
| **Original (Oct 25–26 winning slates)** | `e45945aa2f01` | 2026-10-25 19:29 UTC | Raw stage-3 margin/total vs consensus; **≥3 pt** gap; highest-gap spread or total wins. No injury layer on picks (#107 merged Oct 27). |
| **Pre–#116 snapshot (injury-adj, no later gates)** | `b913bcb25311` | 2026-10-28 05:42 UTC | Injury-adjusted margin/total vs line; **≥3 pt**; no raw-gap gate; DTD weight **0.45**; no 0.5× injury scale (#116/#117 not yet on main). |

Note: Jason’s **4–1** and **5–1** nights match the **Oct 25–26 ET** official backfill (not Oct 21–24). Those slates predate injury-adjusted Pace (#107).

## Sample coverage

- ESPN completed regular-season games through **2026-10-28** (ET): **68**
- Games with **repo** pre-tip lines: **31**
- Games with **ESPN pickcenter** backfill only: **37**
- **Total with any line (target 68):** **68**
- Still missing lines: **0**

### ESPN line caveat

ESPN summary `pickcenter` numbers are usually **closing** (sometimes **open**) DraftKings/ESPN BET lines — **not** T−1h pre-tip consensus. For ESPN-only games, the same line is used for model gap **and** grading (optimistic bias vs real CLV). Repo lines are pre-tip merged scans where available.

## Head-to-head summary (all 68 games; spread + total may both qualify)

| Model | W–L | Plays | Units @ 1u −110 | Wilson 95% CI |
|-------|-----|-------|-----------------|---------------|
| Original (raw, pre-injury) | 33-33 | 66 | -3.00u | 38.3–61.7% |
| Original (inj-adj @ b913bcb) | 35-34 | 69 | -2.18u | 39.2–62.2% |
| Current live (raw) | 33-33 | 66 | -3.00u | 38.3–61.7% |
| Current live (injury-adj + raw gate) | 33-32 | 65 | -2.00u | 38.9–62.5% |
| 2026-27 totals shadow | 28-30 | 58 | -4.55u | 35.9–60.8% |

### By line source (original raw + current injury-adj)

| Line source | Games | Original raw W–L / u | Current inj-adj W–L / u |
|-------------|-------|----------------------|-------------------------|
| Repo pre-tip | 31 | 10-14 / -4.91u | 10-13 / -3.91u |
| ESPN pickcenter | 37 | 23-19 / +1.91u | 23-19 / +1.91u |

#### Subset detail — original raw

- **Repo:** spreads **4-7** (-3.36u), totals **6-7** (-1.55u); Over **2-4** / Under **4-3**; gaps 3–5 **3-7**, 5–8 **5-5**, 8+ **2-2**
- **ESPN:** spreads **9-8** (+0.18u), totals **14-11** (+1.73u); Over **3-5** / Under **11-6**; gaps 3–5 **12-11**, 5–8 **9-5**, 8+ **2-3**

### By market (plays taken)

| Model | Spreads W–L | Spreads u | Totals W–L | Totals u |
|-------|-------------|-----------|------------|----------|
| Original (raw, pre-injury) | 13-15 | -3.18 | 20-18 | +0.18 |
| Original (inj-adj @ b913bcb) | 14-15 | -2.27 | 21-19 | +0.09 |
| Current live (raw) | 13-15 | -3.18 | 20-18 | +0.18 |
| Current live (injury-adj + raw gate) | 13-14 | -2.18 | 20-18 | +0.18 |
| 2026-27 totals shadow | 0-0 | +0.00 | 28-30 | -4.55 |

### Gap buckets (injury-adj gap for current; raw gap for original raw)

| Model | 3–5 | 5–8 | 8+ |
|-------|-----|-----|-----|
| Original (raw, pre-injury) | 15-18 | 14-10 | 4-5 |
| Current live (injury-adj + raw gate) | 15-18 | 14-10 | 4-4 |
| 2026-27 totals shadow | 5-3 | 5-6 | 18-21 |

### Totals: Over vs Under (current injury-adj)

- Over: **5-9**, -4.45u
- Under: **15-9**, +4.64u

## Early official slates (replay check)

- **2026-10-25 ET** original raw: **3-3 (6 plays)** (official backfill **4–1**; DET −1.5 was manual sub-threshold)
- **2026-10-26 ET** original raw: **5-1 (6 plays)** (official backfill **5–1**)

## Oct 28 totals (DEN/NOP, LAL/LAC)
- DEN @ NOP Over: original=yes, current_inj=yes
- LAL @ LAC Over: original=yes, current_inj=yes

## Sample-size / break-even caveats

- Break-even at −110 is **52.38%** (shown as **52.4%**).
- Original raw: **50.0%** on **66** plays → Wilson 95% CI **38.3–61.7%** (includes 52.4% — cannot reject luck).
- Original at or below break-even on this sample; early hot streak alone is not evidence of skill.
- Current injury-adj: **33-32**, **-2.00u** on **65** plays — underperforms original raw on same slates in this replay.

## Plain-English verdict

With **68** games lined (**31** repo + **37** ESPN), original raw is **33-33 (-3.00u)** on **66** plays — still **below break-even**; Wilson 95% CI spans 52.4%. Repo-only subset: **10-14 (-4.91u)**; ESPN pickcenter subset: **23-19 (+1.91u)** (ESPN lines are likely closes, so this subset is useful for coverage but not for claiming CLV). Current injury-adj + raw gate: **33-32 (-2.00u)**. The Oct 25–26 hot start does **not** extend to the full 68-game sample — treat early wins as **small-n variance**, not validated skill.

ESPN backfill file: `data/paper/nba_espn_pregame_lines.json`
Per-play CSV: `data/paper/nba_pace_original_backtest.csv`

