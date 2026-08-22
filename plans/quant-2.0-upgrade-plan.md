# Sharp Scout — "NFL Quant 2.0" Upgrade Plan

**Status:** Proposed (design only — no code changes yet)
**Author:** Sharp Scout maintainer, from feedback by Tom (`Quant_Additions_NFL`)
**Last updated:** 2026-08-22

This plan captures five proposed upgrades, the data required for each, where to source
it, the cost to build and run, and a sequenced implementation roadmap. It is written to be
reviewed by Jason and Tom before any code is written.

**Core principle preserved:** bottom-up first (fundamentals → simulation → market → filter),
signals only, no auto-betting. Every addition is a layer on top of the existing ridge/EPA
baseline, never a replacement.

---

## 1. Executive summary

| # | Feature | Value | Build effort | New run cost |
|---|---|---|---|---|
| 1 | Closing Line Value (CLV) tracking | Very high (earliest proof of real edge) | ~1 session | $0 |
| 2 | Steam detection | High | ~1–2 sessions | ~$0 |
| 3 | "Why is our model wrong?" disagreement classifier | High (compounding) | ~1 session | $0 |
| 4 | Probability calibration + walk-forward backtest | High (measurement backbone) | ~2 sessions | ~$0 |
| 5 | Matchup-interaction ML engine | Highest (but unproven) | ~3–4 sessions, gated on #4 | $0 |

**The single most important cost fact:** running Sharp Scout weekly costs **~$0 in
compute/AI** — it is plain Python on GitHub Actions (free for public repos). The only
recurring expense is the odds-data subscription already being paid (~$99/mo, in season
only). None of these features meaningfully change that.

**Recommended sequence:** 1 → 3 → 2 → 4, then decide on 5 using backtest evidence.

---

## 2. Current system (baseline) — what already exists

| Phase | Module | Role |
|---|---|---|
| 1 Ratings | `src/sharp_scout/phase1/ratings.py` | Opponent-adjusted ridge EPA/success/YPP power ratings + QB starter/backup split. `matchup_means()` is **purely additive**. |
| 2 Monte Carlo | `src/sharp_scout/phase2/monte_carlo.py` | Correlated gamma score sims → `P_true`, cover/over grids. |
| 3 Market | `src/sharp_scout/phase3/market.py` | No-vig devig (multiplicative + power/Shin), sharp consensus, EV. |
| 4 Filter | `src/sharp_scout/phase4/filters.py` | RLM + money/ticket gap. Docstring mentions "steam" but it is **not implemented**. |
| Props | `src/sharp_scout/props/` | Usage → NegBin/Gamma sim → cross-market EV → news/weather filter. |
| Ledger | `src/sharp_scout/ledger/tracker.py` | Play history, settlement, W-L/PnL, per-stage records. **No CLV, no closing line.** |
| Line memory | `src/sharp_scout/data/line_memory.py` | Stores first-seen ("open") line per game/market — **single value, no timestamps.** |
| Site | `src/sharp_scout/site/build.py` | Static GitHub Pages board under `docs/`. |
| Scheduler | `src/sharp_scout/scheduler/` | T-12h/T-3h/T-1h pregame windows via run plan. |

Data sources today: The Odds API (`data/odds_api.py`, Pinnacle via `eu` region + US retail
+ NFL props), Action Network splits (`data/action_network.py`), nflverse PBP/schedules
(`data/nflfastr.py`). All run on GitHub Actions (`.github/workflows/pipeline.yml`,
`pregame.yml`).

---

## 3. Data sourcing (feasibility-critical)

| Feature | Data needed | Source | Cost | In-season freshness |
|---|---|---|---|---|
| CLV | Closing line at kickoff | The Odds API `/odds` (already used) | $0 extra | Real-time |
| Steam | Timestamped line history across sharp books | Odds API **aggregate** `/odds` poll + free Action Network `line_history` | ~$0 | Real-time |
| Disagreement | `p_true` vs `p_mkt` (internal) + weather/QB flags | Internal + nflverse PBP (`roof/temp/wind` already loaded) | $0 | Real-time |
| Calibration | Historical `p_true` vs outcomes | Own ledger | $0 | Grows over season |
| Backtest | Historical PBP + historical odds | nflverse (free) + Odds API historical (10× credits, bounded one-time) | Low | Offline |
| **Matchup engine** | Coverage shell, man/zone, pressure, blitz, personnel | **nflverse `load_ftn_charting` (2022+) + `load_participation` (2023+)**; NGS weekly `load_nextgen_stats` | **$0** | ⚠️ see 3.1 |

### 3.1 The one hard constraint — scheme data lags in-season

The free scheme/coverage/pressure fields (`defense_coverage_type`,
`defense_man_zone_type`, `was_pressure`, blitz/personnel) exist via nflverse
(`load_ftn_charting`, `load_participation`), licensed CC-BY-SA 4.0 (**attribution: "FTN
Data via nflverse"** required). **However, they publish only *after the season ends* — they
do not update week-to-week during the season.**

What *does* update nightly in-season, free: **NGS weekly aggregates**
(`load_nextgen_stats`) — time-to-throw, pressure rates, etc. (player/week level, not
play-level coverage shells).

**PFF+** has in-season charting but is a **$90–120/yr consumer subscription with no data
API/export**; automated ingestion would require ToS-violating scraping. **Rejected** for
automation.

**Design consequence:** the matchup engine builds **team-level scheme *tendency* priors
from completed prior seasons** (free FTN/participation), then updates them in-season with
free nightly NGS aggregates + current-season EPA. This delivers the interaction modeling
Tom wants at **$0 recurring cost**, accepting that exact this-week coverage-shell data
lags. This is the correct trade-off.

Python access: `nflreadpy` (Polars-based port of nflreadr) exposes `load_ftn_charting`,
`load_participation`, `load_nextgen_stats`.

---

## 4. Feature designs

### 4.1 CLV tracking (do first)
- **New ledger fields:** `close_line`, `close_price`, `clv_points`, `clv_pct` per play.
- **Capture:** a kickoff-time (T-0 / final T-1h) snapshot step in the scheduler/settle path;
  reuse the "snapshot lines to disk" pattern already in `data/line_memory.py`.
- **Math:** CLV points = `bet_line − close_line` (side-adjusted). CLV% =
  `p_close_novig − p_bet_novig` using existing `power_devig()` in `phase3/market.py`.
- **Output:** CLV column + rolling-average CLV on the Pages board. This is the earliest
  statistically meaningful proof the process beats the market, long before W-L converges.
- **Files:** `ledger/tracker.py`, `scheduler/`, `site/build.py`. **No new dependency.**

### 4.2 Steam detection
- **Infra change:** extend `data/line_memory.py` from single first-seen value → **append-only
  timestamped samples** per game/market/book.
- **Signal:** `steam = magnitude × speed × n_sharp_books_moving × confirmation`, surfaced as
  a Phase-4 confirmation flag beside RLM in `phase4/filters.py`.
- **Cost control:** poll the **aggregate** `/odds` endpoint (all games, one call ≈ markets ×
  regions credits), **never per-event**, in the pre-kick window. ~30 polls × ~4 credits ≈
  120 credits/slate — negligible. Action Network `line_history` is a free secondary source.
- **Note:** steam (velocity across sharp books) ≠ RLM (direction vs public); they complement.

### 4.3 "Why is our model wrong?" disagreement classifier
- **Trigger:** when `abs(p_true − p_mkt)` clears a threshold (you already compute `vs_sharp`
  in `phase4/filters.py`), write a `disagreement` record.
- **Auto-tag `category`** (heuristic start): `weather` if wind ≥ 15, `qb` if backup flag,
  `injury` if in `INACTIVE_PLAYERS`, else `unknown`; plus a manual-override field.
  Category set from Tom: injury, QB, weather, matchup, scheme, market overreaction, public
  bias, model deficiency, sample-size, usage change, coaching change, unknown.
- **Home:** `copy/explain.py` + a new ledger sub-table.
- **Payoff:** over a season, reveals which disagreement types are real edges vs. model
  naivety — the evidence needed to decide whether 4.5 is worth trusting.

### 4.4 Calibration + walk-forward backtest (measurement backbone)
- **Calibration:** bin historical `p_true`, compare to realized frequency (reliability curve
  + Brier score); apply isotonic/Platt correction if miscalibrated. Uses `scikit-learn`
  (already a dependency).
- **Backtest:** replay ratings → MC → market → filter week-by-week on nflverse PBP + Odds
  API **historical** odds (10× credits, bounded one-time backfill). This is the gate that
  validates any model change — especially 4.5 — before it goes live.

### 4.5 Matchup-interaction ML engine (biggest; gate behind 4.4)
- **Design:** a **residual/adjustment layer on top of** the ridge/EPA `matchup_means()` —
  never a replacement (Tom's guardrail). `lightgbm` gradient boosting on interaction
  features: QB EPA-under-pressure × opp pressure rate; pass-rate-over-expected × coverage
  tendency; gap vs zone rush × front; etc. — built from the free nflverse scheme priors
  (§3.1) + current-season EPA.
- **Overfitting control:** ~272 games/season is little data — monotonic constraints, heavy
  regularization, and the 4.4 backtester as arbiter. **Do not build until 4.4 exists.**
- **Cost:** `lightgbm` trains in seconds on GitHub Actions. $0 recurring.

---

## 5. Cost model

### 5.1 Weekly RUN cost (recurring) — the primary concern

| Item | Cost | Notes |
|---|---|---|
| GitHub Actions compute | **$0** | Public repo = unlimited free minutes. |
| nflverse (PBP/NGS/FTN/schedules) | **$0** | Free parquet, cached in `data/pbp_cache/`. |
| Action Network splits + line history | **$0** | Cookie-based, already integrated. |
| The Odds API | **~$99/mo, in season only** | Already paid; gives Pinnacle + NFL props. New features add ~0. |
| Cursor/Opus/Composer to *run* | **$0** | Running uses **no AI** — it's Python. |

**Odds API credit math:** aggregate `/odds` returns the whole slate for `markets × regions`
credits (~9), not per game. Current cadence sits comfortably in a 200k/mo tier. Steam is the
only cost lever and is ~120 credits/slate if aggregate-polled. **Running weekly is not
expensive and stays that way.**

### 5.2 One-time BUILD cost (in Cursor)

- **Composer 2.5** covers ~80% (CLV, steam plumbing, disagreement logging, ledger/site,
  tests). In Cursor's included "Cursor Models" pool — effectively covered by Pro. ~$0.50/$2.50
  per M tokens (~10–30× cheaper than Opus).
- **Claude Opus** only for hard reasoning: matchup ML architecture (4.5) + calibration math
  (4.4). Billed from the "Other Models" pool at API rates ($5/$25 per M). Use surgically.

---

## 6. Cursor / tooling guidance

| Question | Answer |
|---|---|
| Can I use Composer? | Yes — for the bulk of the build. |
| Do I need Opus? | Only for 4.4 math and 4.5 ML design. |
| Which Cursor plan? | **Pro ($20/mo)** is sufficient. Ultra not needed. |
| Local or cloud agents (build)? | Either; **local Composer is cheapest**. Cloud agent on `psudad/sharp-scout` → PR is a clean workflow since the remote is source of truth. |
| Local or cloud (run)? | **Neither** — runs on GitHub Actions. |

---

## 7. Implementation roadmap

| # | Feature | Effort | Build model | New deps | Recurring cost |
|---|---|---|---|---|---|
| 1 | CLV tracking | ~1 session | Composer | none | $0 |
| 2 | Timestamped line history → steam | ~1–2 sessions | Composer | none | ~$0 |
| 3 | Disagreement classifier (logging) | ~1 session | Composer | none | $0 |
| 4 | Calibration + walk-forward backtest | ~2 sessions | Composer + some Opus | none (sklearn exists) | ~$0 (one-time historical backfill) |
| 5 | Matchup-interaction ML engine | ~3–4 sessions, gated on #4 | Opus (design) + Composer (impl) | `lightgbm`, `nflreadpy` | $0 |

**Order:** 1 → 3 → 2 → 4, then reassess 5 with backtest evidence. Each item ships as a
feature branch → PR into the remote (`develop`/`main` per repo convention), keeping the
remote authoritative.

---

## 8. Open decisions for Jason / Tom

1. Confirm **PFF is out** for automation (recommended) and the free nflverse scheme-priors
   approach (§3.1) is acceptable given the in-season lag.
2. Confirm **CLV (#1) is the first build**.
3. Confirm target for the walk-forward backtest historical-odds backfill (how many prior
   seasons) before spending historical credits.
4. Confirm whether the disagreement classifier categories (§4.3) match how Tom wants to
   review model misses.
