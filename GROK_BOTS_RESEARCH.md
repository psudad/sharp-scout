# Sharp Scout — Grok Bots Research Brief

Answers for researchers who need to read the codebase and understand what the system does today.

---

## 1. Where does Sharp Scout live?

**Primary home: a public GitHub repository.**

| Item | Value |
|------|--------|
| **GitHub repo** | [https://github.com/psudad/sharp-scout](https://github.com/psudad/sharp-scout) |
| **Default branch** | `main` |
| **Live public board (GitHub Pages)** | [https://psudad.github.io/sharp-scout/](https://psudad.github.io/sharp-scout/) |

Sharp Scout is **not** a separate hosted “Cursor cloud product.” It is a **single Python package** you clone and run locally (or on a **Cursor Cloud Agent** pointed at the same GitHub repo). There is no separate frontend repo or build step beyond regenerating static HTML under `docs/`.

### Repository layout (where the algorithms live)

| Path | Purpose |
|------|---------|
| `src/sharp_scout/` | All production logic (install as editable package `sharp-scout`) |
| `src/sharp_scout/phase1/` | Fundamental ratings (EPA / success / YPP), optional scheme + matchup ML residual |
| `src/sharp_scout/phase2/` | Monte Carlo score simulation → model spread, total, `P_true` |
| `src/sharp_scout/phase3/` | Market EV vs sharp no-vig lines |
| `src/sharp_scout/phase4/` | Split filter (Action Network), RLM, steam detection |
| `src/sharp_scout/data/` | External data clients (Odds API, Action Network, nflverse/cfbfastR, ESPN, line store) |
| `src/sharp_scout/ledger/` | Play ledger, settlement helpers, CLV grading |
| `src/sharp_scout/props/` | Player-props engine (usage → sim → EV) |
| `src/sharp_scout/pipeline/` & `src/sharp_scout/ncaaf/` | NFL and NCAAF orchestration |
| `src/sharp_scout/site/` | Static GitHub Pages site builder |
| `src/sharp_scout/api/` | Optional FastAPI server + dashboard |
| `scripts/` | CLI entrypoints (`run_pipeline.py`, `run_ncaaf.py`, `settle_now.py`, etc.) |
| `tests/` | Offline pytest suite |
| `data/` | JSON ledgers, SQLite DB, calibration artifacts (runtime + tracked history) |
| `docs/` | Generated public site (NFL + CFB tabs, ledger, record) |
| `README.md`, `AGENTS.md`, `plans/` | Operator docs and upgrade plans |

**How to read the code locally**

```bash
git clone https://github.com/psudad/sharp-scout.git
cd sharp-scout
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Offline demo (no API keys): `python scripts/run_pipeline.py --demo --build-site`  
Full narrative: start at `README.md`, then trace `scripts/run_pipeline.py` → `sharp_scout.pipeline.run`.

**Automation:** GitHub Actions workflows under `.github/workflows/` run live pipelines, pregame windows, settlement, and Pages deploy when secrets are configured on the repo.

---

## 2. What does the system do today?

Sharp Scout is an **NFL + NCAA football betting signal pipeline** — **signals and tracking only; it does not place bets.**

End-to-end behavior:

1. **Pull market odds** from books (via aggregator).
2. **Build its own lines and probabilities** from play-by-play fundamentals + Monte Carlo.
3. **Find expected-value edges** vs a **sharp no-vig benchmark** (Pinnacle preferred; Circa when available).
4. **Filter** with public-betting splits and line-movement confirmations.
5. **Track picks** in JSON ledgers, **settle** against final scores, publish **W–L / units / CLV** on GitHub Pages.

### Four-phase sides pipeline (NFL and NCAAF)

Architecture is **bottom-up**: market data informs filtering; the model baseline is built from fundamentals first.

| Phase | What it does | Main code |
|-------|----------------|-----------|
| **1 — Ratings** | Opponent-adjusted EPA / success / yards-per-play power ratings | NFL: nflverse PBP (`data/nflfastr.py`); NCAAF: cfbfastR / sportsdataverse (`data/cfbfastr.py`) |
| **2 — Monte Carlo** | Correlated score sims → model spread/total and cover/win `P_true` | `phase2/monte_carlo.py` |
| **3 — Market EV** | No-vig sharp line from odds → `EV = P_true × decimal − 1`; flag candidates above threshold | `phase3/market.py`, `data/odds_api.py` |
| **4 — Split filter** | Require reverse line movement **or** money−ticket gap; optional steam confirmation | `phase4/filters.py`, `data/action_network.py`, `phase4/steam.py` |

**Validated plays** are appended to:

- NFL: `data/ledger.json`
- NCAAF: `data/ncaaf_ledger.json`

**Settlement** grades finished games using public final scores (no odds API key required for settle-only runs), e.g. `scripts/settle_now.py` / `scripts/settle_plays.py` (ESPN, nflverse, cfbfastR sources as implemented in `data/`).

**Stage picks:** For each game the pipeline also records independent “lens” picks (`model`, `sharp`, `public`, `money`, `sharp_edge`, `rlm`, `hybrid`) for research comparison — see `stage_picks.py` and the site **Stages** tab.

### Player props (NFL)

Separate engine under `src/sharp_scout/props/`:

1. Usage / efficiency from nflverse PBP  
2. Non-normal Monte Carlo (NegBin / Gamma)  
3. EV vs Odds API player prop markets  
4. News/weather-style filters (e.g. inactive list, wind)

**Note:** Props default to **shadow mode** (`PROPS_PUBLISH_ENABLED=false` in `.env.example`) — artifacts are written for review but picks are not published to the ledger/board until explicitly enabled.

### Quant 2.0 layers (on top of the baseline)

Documented in `README.md` and `plans/quant-2.0-upgrade-plan.md`, including:

- **Closing line value (CLV)** — `ledger/clv.py`, timestamped line history in `data/line_store.py`
- **Steam detection** — `phase4/steam.py`
- **Model vs market disagreement logging** — `analysis/disagreement.py`
- **Calibration / walk-forward backtest** — `analysis/calibration.py`, `backtest/walk_forward.py`
- **Matchup residual ML** (optional) — `phase1/matchup_ml.py`, `phase1/scheme.py`

### Data sources and APIs

| Source | Role | Config / notes |
|--------|------|----------------|
| **[The Odds API](https://the-odds-api.com)** | Live odds: NFL `americanfootball_nfl`, NCAAF `americanfootball_ncaaf`; regions `us`, `us2`, `eu` for retail + Pinnacle | `ODDS_API_KEY`; client in `data/odds_api.py` |
| **Action Network** | Ticket % vs money % (handle), public betting scoreboard | `ACTION_NETWORK_TOKEN` (preferred Bearer JWT) or `ACTION_NETWORK_COOKIE`; `data/action_network.py`. Unofficial API; may require Pro/EDGE session |
| **nflverse** | NFL play-by-play parquet for ratings and props usage | `data/nflfastr.py` |
| **cfbfastR / sportsdataverse** | College PBP for NCAAF ratings | `data/cfbfastr.py` |
| **ESPN** | Scores / schedule helpers where used | `data/espn_nfl.py`, `data/espn_cfb.py` |
| **Manual slate JSON** | Preseason or pasted odds when Odds API has no market | `scripts/run_manual_slate.py`, `data/manual_odds.py` |
| **Local persistence** | Deduped history, line snapshots | `data/sharp_scout.db` (SQLite), `data/line_store.py`, ledgers above |

**Sharp benchmark:** Pinnacle via Odds API `eu` region is the reliable sharp reference; Circa is preferred in code order when the aggregator returns it.

**Demo mode:** `--demo` uses mock odds/splits and neutral ratings so the full pipeline runs **offline** without keys (see `AGENTS.md`). Demo mutates tracked `data/*.json` and `docs/` — revert before committing unrelated work.

### What runs in production

- **Scheduled GitHub Actions:** daily slate refresh, NCAAF pipeline, pregame T-12h / T-3h / T-1h windows, settlement, site rebuild (see README workflow table).
- **Optional local API:** `uvicorn sharp_scout.api.main:app` — health, trigger runs, read latest signals/plays/ratings/splits.

### Explicit non-goals

- No sportsbook integration or automated wagering.
- Research / decision-support only; obey local law and book terms.

---

## Quick pointers for algorithm research

1. Read pipeline orchestration: `src/sharp_scout/pipeline/run.py` (NFL), `src/sharp_scout/ncaaf/pipeline.py` (NCAAF).
2. Read EV and no-vig math: `src/sharp_scout/utils/odds.py`, `src/sharp_scout/phase3/market.py`.
3. Read validation rules: `src/sharp_scout/phase4/filters.py`, thresholds in `src/sharp_scout/config.py` / `.env.example`.
4. Run tests: `pytest -q` (fully offline).

For operator commands and cloud-agent caveats, see `AGENTS.md` in the repo root.
