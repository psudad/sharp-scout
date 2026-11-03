# NBA Pace filter backtest (research — PR #122)

**Universe:** 68 games (repo **31** + ESPN pickcenter **37**). ESPN lines are usually **closes**, not pre-tip. **No Odds API.**

## 1 — Side filters (baseline = all qualifying spread/total plays)

| Model | Filter | W–L | Win % | Units | $ @ $10/u | n | Wilson 95% |
|-------|--------|-----|-------|-------|-----------|---|------------|
| Original raw (e45945a) | baseline | 33-33 | 50.0% | -3.00 | $-30 | 66 | 38.3–61.7% |
| Original raw (e45945a) | unders_only | 28-24 | 53.8% | +1.45 | $+15 | 52 | 40.5–66.7% |
| Original raw (e45945a) | strict_overs_2x_gap | 1-1 | 50.0% | -0.09 | $-1 | 2 | 9.5–90.5% |
| Current injury-adj + raw gate | baseline | 33-32 | 50.8% | -2.00 | $-20 | 65 | 38.9–62.5% |
| Current injury-adj + raw gate | unders_only | 28-23 | 54.9% | +2.45 | $+25 | 51 | 41.4–67.7% |
| Current injury-adj + raw gate | strict_overs_2x_gap | 1-1 | 50.0% | -0.09 | $-1 | 2 | 9.5–90.5% |
| 2026-27 totals shadow | baseline | 28-30 | 48.3% | -4.55 | $-45 | 58 | 35.9–60.8% |
| 2026-27 totals shadow | unders_only | 17-21 | 44.7% | -5.55 | $-55 | 38 | 30.1–60.3% |
| 2026-27 totals shadow | strict_overs_2x_gap | 6-8 | 42.9% | -2.55 | $-25 | 14 | 21.4–67.4% |

## 2 — Totals minimum gap (totals plays only)

| Model | Min gap | W–L | Win % | Units | $ | n |
|-------|---------|-----|-------|-------|---|---|
| Original raw (e45945a) | ≥2 pt | 20-18 | 52.6% | +0.18 | $+2 | 38 |
| Original raw (e45945a) | ≥3 pt | 20-18 | 52.6% | +0.18 | $+2 | 38 |
| Original raw (e45945a) | ≥4 pt | 15-10 | 60.0% | +3.64 | $+36 | 25 |
| Original raw (e45945a) | ≥5 pt | 11-7 | 61.1% | +3.00 | $+30 | 18 |
| Original raw (e45945a) | ≥6 pt | 7-3 | 70.0% | +3.36 | $+34 | 10 |
| Current injury-adj + raw gate | ≥2 pt | 20-18 | 52.6% | +0.18 | $+2 | 38 |
| Current injury-adj + raw gate | ≥3 pt | 20-18 | 52.6% | +0.18 | $+2 | 38 |
| Current injury-adj + raw gate | ≥4 pt | 15-10 | 60.0% | +3.64 | $+36 | 25 |
| Current injury-adj + raw gate | ≥5 pt | 11-7 | 61.1% | +3.00 | $+30 | 18 |
| Current injury-adj + raw gate | ≥6 pt | 7-3 | 70.0% | +3.36 | $+34 | 10 |
| 2026-27 totals shadow | ≥2 pt | 28-30 | 48.3% | -4.55 | $-45 | 58 |
| 2026-27 totals shadow | ≥3 pt | 28-30 | 48.3% | -4.55 | $-45 | 58 |
| 2026-27 totals shadow | ≥4 pt | 24-29 | 45.3% | -7.18 | $-72 | 53 |
| 2026-27 totals shadow | ≥5 pt | 23-27 | 46.0% | -6.09 | $-61 | 50 |
| 2026-27 totals shadow | ≥6 pt | 21-26 | 44.7% | -6.91 | $-69 | 47 |

## 3 — Rest / travel (market totals vs line, all games with total)

- **All games (Over):** 30-37-1 (44.1%), -9.73u ($-97), **n=68**
- **All games (Under):** 37-30-1 (54.4%), +3.64u ($+36), **n=68**
- **Either team B2B (Over):** 9-9 (50.0%), -0.82u ($-8), **n=18**
- **Either team B2B (Under):** 9-9 (50.0%), -0.82u ($-8), **n=18**
- **Rest mismatch (Over):** 1-1 (50.0%), -0.09u ($-1), **n=2**
- **Rest mismatch (Under):** 1-1 (50.0%), -0.09u ($-1), **n=2**

### Model: Unders only + either team B2B

- **Original raw (e45945a):** 2-4, -2.18u ($-22), n=6
- **Current injury-adj + raw gate:** 2-4, -2.18u ($-22), n=6
- **2026-27 totals shadow:** 3-6, -3.27u ($-33), n=9

## 4 — CLV (original raw; open + close both required)

- Plays with open+close: **55** (small n; repo first-scan open vs graded close; ESPN open/close from pickcenter)
- Line moved toward model (CLV proxy): **15/55** (27.3%)
- Record on those plays: **31-24**, +4.18u ($+42)

## Summary table (key filters)

| Model | Filter | W–L | Win % | Units | $ @ $10/u | n |
|-------|--------|-----|-------|-------|-----------|---|
| Original raw (e45945a) | baseline | 33-33 | 50.0% | -3.00 | $-30 | 66 |
| Original raw (e45945a) | unders_only | 28-24 | 53.8% | +1.45 | $+15 | 52 |
| Original raw (e45945a) | strict_overs_2x_gap | 1-1 | 50.0% | -0.09 | $-1 | 2 |
| Original raw (e45945a) | totals_min_gap_5 | 11-7 | 61.1% | +3.00 | $+30 | 18 |
| Original raw (e45945a) | totals_min_gap_6 | 7-3 | 70.0% | +3.36 | $+34 | 10 |
| Original raw (e45945a) | unders_either_b2b | 2-4 | 33.3% | -2.18 | $-22 | 6 |
| Current injury-adj + raw gate | baseline | 33-32 | 50.8% | -2.00 | $-20 | 65 |
| Current injury-adj + raw gate | unders_only | 28-23 | 54.9% | +2.45 | $+25 | 51 |
| Current injury-adj + raw gate | strict_overs_2x_gap | 1-1 | 50.0% | -0.09 | $-1 | 2 |
| Current injury-adj + raw gate | totals_min_gap_5 | 11-7 | 61.1% | +3.00 | $+30 | 18 |
| Current injury-adj + raw gate | totals_min_gap_6 | 7-3 | 70.0% | +3.36 | $+34 | 10 |
| Current injury-adj + raw gate | unders_either_b2b | 2-4 | 33.3% | -2.18 | $-22 | 6 |
| 2026-27 totals shadow | baseline | 28-30 | 48.3% | -4.55 | $-45 | 58 |
| 2026-27 totals shadow | unders_only | 17-21 | 44.7% | -5.55 | $-55 | 38 |
| 2026-27 totals shadow | strict_overs_2x_gap | 6-8 | 42.9% | -2.55 | $-25 | 14 |
| 2026-27 totals shadow | totals_min_gap_5 | 23-27 | 46.0% | -6.09 | $-61 | 50 |
| 2026-27 totals shadow | totals_min_gap_6 | 21-26 | 44.7% | -6.91 | $-69 | 47 |
| 2026-27 totals shadow | unders_either_b2b | 3-6 | 33.3% | -3.27 | $-33 | 9 |

## Plain-English verdict

Sample sizes stay **small** (baseline **n≈66** per spread+total model; **strict 2× Overs n=2** for raw/current; **totals ≥6 n=10**). Wilson intervals still span break-even (~52.4% at -110).

**Unders-only** is the only side filter that consistently improves on baseline in this slice: original raw **28-24** (+1.45u, $+15, n=52); current injury-adj **28-23** (+2.45u). **Strict Overs (gap ≥6)** is too thin to judge (n=2). The **2026-27 totals shadow** gets worse under Unders-only — do not apply these filters to that sidecar yet.

**Totals gap ≥5–6** on original/current (totals market only) shows **7-3** and +3.36u but **n=10** — interesting for **paper/shadow** only if you also require **repo pre-tip lines** (not ESPN closes). **Rest/B2B**: market Unders on B2B slates were **9-9** (coin flip); **model Unders + B2B** was **2-4** (n=6) — **not** worth stacking live.

**CLV caveat:** ESPN pickcenter numbers are often **closing** lines; open+close CLV on 55 plays showed the line moved toward the model only **~27%** of the time — do not treat CLV as validation on the ESPN subset.

**Shadow-test recommendation (not production):** after the Nov 5 resume, log **Unders-only** plays from **current injury-adj Pace** on **repo scans only**, optionally tag **totals with gap ≥5** separately. Skip B2B stacking and skip strict-Overs until n grows.

CSV: `data/paper/nba_pace_filters_backtest.csv`

