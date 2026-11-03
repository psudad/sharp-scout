# Pace of Play diagnosis — Oct 28, 2026 (for Jason Eger)

Plain-language post-mortem for the official **Pace of Play model** card (not Sharp Scout price-edge picks). Numbers below come from the repo’s replay engine at tip, ESPN finals, and the corrected official ledger after this fix PR.

## What happened on Oct 28?

The card went **1–3 on totals** (only play type published that night): **GSW@MIN Over 227.5** won; **DEN@NOP Over 240.5**, **NYK@CHI Under 233.5**, and **LAL@LAC Over 224.5** lost. That followed **Oct 27** spread losses (**BOS -12.5**, **DET +4.25**) — **five straight official losses** before the MIN win.

**Corrected official record through Oct 28:** **10–7, +2.09u** at 1u -110 (Oct 27 card is **BOS + DET only** under raw-gap rules; Oct 28 is the four evening totals from the ~6:20 PM ET manual FanDuel card).

## Oct 28 totals — model vs line vs actual

| Game | Play | Injury-adj proj total | Line | Actual | Result |
|------|------|----------------------|------|--------|--------|
| GSW @ MIN | Over 227.5 | **233.8** | 227.5 | 233 | **W** |
| DEN @ NOP | Over 240.5 | **246.4** | 240.5 | 195 | **L** |
| NYK @ CHI | Under 233.5* | **227.7** | 233.5 | 260 | **L** |
| LAL @ LAC | Over 224.5 | **233.9** | 224.5 | 190 | **L** |

\*Official grade uses **233.5** (consensus at card time); manual JSON had 232.5 — same side/gap band.

### What drove each projection (same engine for all four)

- **Sample window:** Early season (~first 2–4 games per team); ratings are **heavily blended toward 2025–26 priors** and league averages, so pace/ORTG/DRTG move slowly.
- **Pace + efficiency:** Base total = blended **pace × (home ORTG + away ORTG) / 100**, with schedule/rest layers mostly on spreads; totals lean on pace×efficiency.
- **Injuries:** Day-to-day weight **0.18** (halved until 50 graded official plays). Oct 28 scans had ESPN absence lists; injury-adjusted totals differ from raw by only **~0–1.5 pts** on these four — **not** the main story vs 30–40 pt misses.
- **Lines on the card:** FanDuel **manual** snapshot (~6:20 PM ET) after Odds API game lines did not refresh; projections still used the walk-forward engine at that snapshot.

**GSW @ MIN:** Model and market aligned on a high total; actual **233** landed near projection — good process, small margin.

**DEN @ NOP, LAL @ LAC (Over losses):** Model **overs** by **~44–51 pts** vs actual. The engine still had **mid-230s / mid-240s** totals from **prior-season-style pace/efficiency** while games finished **190–195** (slow, low-efficiency nights). That pattern looks like **early-season prior bias + pace/over tail**, not a bad line read — the market total was already high (240.5 / 224.5) and the model pushed **over** anyway.

**NYK @ CHI (Under loss):** Model **under** by **~32 pts** vs actual (**260**). Projection **227.7** vs line **233.5** — model and play both favored under, but Chicago/NYK played an extreme shootout. Part **variance**, part **under-reaction in fast-updating early-season ORTG** when two teams exceed prior offensive pace.

## Stale lines vs model vs variance (Oct 28 evening)

- **Stale lines:** The **7 PM ET** games never got a new Odds API number (totals unchanged from **~Tue 7:54 PM** scans). The **evening card** used **manual FanDuel** lines; those four plays did **not** rely on the stale Tuesday API quote. Stale lines explain **missing early games on the card**, not the **30+ pt** misses on the four graded totals (model vs actual gap is much larger than line error).
- **Model bias:** Oct 28 totals show **systematic overprojection on two “Over” losses** where actual scoring collapsed — consistent with **early-season pace/ORTG still too hot** vs reality.
- **Variance:** **NYK@CHI** is the clearest high-variance tail; **GSW@MIN** is the counterexample where model, line, and result clustered.

## Oct 25–28 — spreads vs totals (official card only)

| Market | W–L | Notes |
|--------|-----|--------|
| **Spreads** | **5–3** | Oct 25–26 backfill + Oct 27 BOS/DET |
| **Totals** | **5–4** | Includes Oct 28 **1–3** |

Totals account for **all four losses on Oct 28**; spreads contributed the **Oct 27** streak starter. Across the short sample, **totals misses are larger in absolute error** when wrong (especially overs that finish in the 190s).

## Operational issues (fixed in this PR, not model rules)

1. **Official ledger sync crashed** every scan/settle: `mechanical_pace` called `official_pace.pace_display_pick_from_snapshot(..., engine=)` but the wrapper did not forward `engine` → entire **“NBA official pace sync skipped”** path.
2. **`pace_published_pick` was never stored** on freeze, so auto-grade could not run even when sync worked.
3. Some **Oct 28 7 PM** games were **voided as “outside horizon”** and never frozen/graded in the paper store (now **re-eligible** when the first scan was inside the 36h window).
4. **NBA shadow CI** did not commit `nba_pace_of_play_official.*` to Pages (settle job did, but sync was failing).

## Recommendations (evidence-backed — **not implemented**; need your OK)

1. **Separate, higher threshold for totals on the official card** (e.g. 4–4.5 pt injury-adj gap vs 3 pt spreads) — Oct 28 had three totals at **5.6–7.4 pt** gaps that still lost big; raising the bar reduces exposure to **high-variance early-season total tails** without touching spread volume yet.
2. **Shrink injury-adj total toward consensus when team games < 15 and gap > 5** — replay shows **large gaps** on DEN/LAL overs while priors dominate; blending **30–40% to market** on totals only would have cut gap sizes on those plays.
3. **Require a same-day line refresh before a total is publishable** — manual/scan timestamp on the card; avoids betting stale API numbers on early tips (7 PM ET issue) while still **never pausing** Odds API pulls.

---

*Generated during fix PR for Grokky review; model rule changes intentionally omitted from code.*
