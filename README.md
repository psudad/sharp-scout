# Sharp Scout

Institutional-grade **NFL + NCAA football betting signal pipeline** (signals only — no auto-betting).

Architecture runs bottom-up first so market data filters model edges instead of biasing the baseline:

1. **Fundamental engine** — opponent-adjusted EPA / success / YPP power ratings (nflverse play-by-play parquet)
2. **Monte Carlo** — correlated score simulations → model spread/total and `P_true`
3. **Market model** — Pinnacle (and Circa when present) no-vig odds via [The Odds API](https://the-odds-api.com) → EV
4. **Split filter** — Action Network ticket/money % + reverse line movement confirmation

Validated plays are stored in [`data/ledger.json`](data/ledger.json) (NFL) / [`data/ncaaf_ledger.json`](data/ncaaf_ledger.json) (NCAAF) and published to **GitHub Pages** under [`docs/`](docs/).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Add ODDS_API_KEY (required for live odds)
# Preferred: ACTION_NETWORK_TOKEN (Bearer JWT); fallback: ACTION_NETWORK_COOKIE
python scripts/diagnose_action_network.py   # verify money/ticket %

# Demo run + rebuild Pages site (NFL)
python scripts/run_pipeline.py --demo --build-site

# NCAA football (FBS) — same 4-phase engine, separate ledger
python scripts/run_ncaaf.py --demo --build-site
python scripts/diagnose_action_network.py --league ncaaf

# Live run
python scripts/run_pipeline.py --build-site
python scripts/run_ncaaf.py --build-site

# On-demand refresh (settle + both sports + rebuild site)
python scripts/refresh_board.py
# From your phone: GitHub app → psudad/sharp-scout → Actions →
#   "Refresh Board (on demand)" → Run workflow (defaults: NFL + CFB on)

# Preseason / manual pasted odds (The Odds API has no preseason) + live Action Network splits
python scripts/run_manual_slate.py data/manual_slate.example.json --date 20260814 --skip-pbp --build-site

# Settle completed games (nflverse / cfbfastR scores) and refresh site
python scripts/settle_plays.py --build-site
python scripts/settle_plays.py --sport ncaaf --build-site
# Or one game manually:
python scripts/settle_plays.py --manual KC BUF 24 20 --build-site
python scripts/settle_plays.py --sport ncaaf --manual ALA UGA 24 27 --build-site

# Local API (optional)
uvicorn sharp_scout.api.main:app --host 0.0.0.0 --port 8000
```

## NCAA football

NCAAF uses the **same 4-phase sequence** as NFL (ratings → Monte Carlo → sharp no-vig EV → split filter) with college-specific sources:

| Layer | NCAAF |
|---|---|
| Ratings | cfbfastR / sportsdataverse play-by-play (`data/cfbfastr.py`) |
| Odds | The Odds API `americanfootball_ncaaf` (Pinnacle + retail) |
| Splits | Action Network league `ncaaf` |
| Ledger | `data/ncaaf_ledger.json` (NFL stays in `data/ledger.json`) |
| Artifacts | `artifacts/latest_ncaaf_signals.json` |
| Site | **CFB** tab on GitHub Pages |

College defaults: HFA 3.0, scoring base 27.5. Team names like “Alabama Crimson Tide” normalize to `ALA`. Demo mode only populates `ALA@UGA`.

```bash
python scripts/run_ncaaf.py --demo --build-site
python scripts/settle_plays.py --sport ncaaf --manual ALA UGA 24 27 --build-site
```

## Stage picks (compare every lens)

For each game the pipeline also picks a side from **each data stage** independently:

| Stage | Winner rule |
|---|---|
| `model` | Monte Carlo / fundamental favorite |
| `sharp` | Pinnacle/Circa no-vig favorite |
| `public` | Ticket-% majority |
| `money` | Handle-% majority |
| `sharp_edge` | Largest positive money − ticket % (Action Network Diff) |
| `rlm` | Reverse line movement side (when present) |
| `hybrid` | Full system validated play, else model+confirmations |

These land in `stage_picks` on the artifact and the **Stages** tab on GitHub Pages, with per-stage W–L after settlement — so you can see when sharps fade the public, when RLM fires, and whether the hybrid agrees.

## Player props

Props reuse the same ledger/Pages board with a separate engine:

1. **Usage** — route/target/air-yards/snap/RZ shares + TPRR/YPRR/CPOE from nflverse PBP  
2. **Non-normal MC** — Negative Binomial (receptions/TDs), Gamma (yards)  
3. **Cross-market EV** — Odds API player props + alternate/tail lines  
4. **News/weather filter** — inactive reallocation (`INACTIVE_PLAYERS`) + wind ≥ 15 mph downgrade  

```bash
python scripts/run_props.py --demo --build-site
```

## Quant 2.0 features (CLV, steam, disagreement, calibration, matchup engine)

Layered on top of the four-phase baseline (see `plans/quant-2.0-upgrade-plan.md`). All run
at ~$0 recurring cost on GitHub Actions.

- **Closing Line Value (CLV)** — `ledger/clv.py`. Every play is graded against the sharp
  closing line (captured from the timestamped line store at the T-1h pregame run). Points +
  price-based CLV appear on the ledger and a summary banner on the Plays tab. This is the
  earliest proof the process beats the market.
- **Steam detection** — `phase4/steam.py`. Sharp line *velocity × breadth* across books,
  a Phase-4 confirmation flag alongside RLM and money/ticket splits. Reads the shared
  timestamped history in `data/line_store.py`.
- **"Why is our model wrong?"** — `analysis/disagreement.py`. Logs every material
  model-vs-market gap with an auto-classified cause (weather, QB, injury, public bias,
  market overreaction, model deficiency, …) and learns each category's hit rate over time.
- **Calibration + walk-forward backtest** — `analysis/calibration.py`,
  `backtest/walk_forward.py`. Fits an isotonic/Platt calibrator from settled history
  (applied at edge discovery; identity until fit) and replays weeks without look-ahead.

```bash
python scripts/fit_calibration.py     # fit data/calibration.json from the ledger
python scripts/backtest.py            # walk-forward over the ledger (or --records-json)
```

- **Matchup-interaction engine** — `phase1/scheme.py`, `phase1/matchup_ml.py`. A **bounded
  residual layer** on top of the additive `matchup_means()` (never a replacement). Uses
  scikit-learn gradient boosting by default (no new runtime dep); LightGBM + nflverse scheme
  enrichment are optional via `pip install -e ".[ml]"`. No trained model → zero adjustment.

```bash
python scripts/train_matchup.py --season 2022 --season 2023 --season 2024
```

## Pregame schedule (T-12h / T-3h / T-1h)

`scripts/run_pregame.py` fires **sides + props** when a game is within ±25 minutes of 12h, 3h, or 1h before kickoff. Fired windows are recorded in `data/schedule_state.json` so each window runs once.

Weekly run times are built from the nflverse schedule (`games.csv`) into `data/pregame_run_plan.json`:

```bash
python scripts/plan_pregame_runs.py   # refresh plan from NFL schedule
python scripts/run_pregame.py --demo
```

GitHub Action **Pregame Windows** checks the run plan hourly on Thu–Mon (most hours exit in seconds). Full pipeline runs only when a planned window is due — typically ~3 runs per kickoff slot (1pm / 4pm / 8pm ET Sunday, etc.), not every 30 minutes.

## GitHub Pages (weekly public board)

### One-time repo setup

1. **Settings → Pages → Build and deployment**
   - Source: **GitHub Actions**
2. **Settings → Secrets and variables → Actions → Repository secrets** — add:
   - `ODDS_API_KEY` (required for live odds on GitHub Actions — a local `.env` file is **not** used in CI)
   - `ACTION_NETWORK_TOKEN` (preferred; Bearer JWT for money/handle %)
   - `ACTION_NETWORK_COOKIE` (optional fallback)
3. Merge this branch to `main`, then run **Actions → NFL Pipeline + Ledger → Run workflow**
4. Site URL: `https://<user>.github.io/sharp-scout/`

### What runs automatically

| Workflow | When | Does |
|---|---|---|
| `Pregame Windows` | Hourly Thu–Mon + plan refresh Monday | Fire T-12h / T-3h / T-1h only when scheduled in run plan |
| `NFL Pipeline + Ledger` | Mon–Sat + Sun game day + manual | Daily slate refresh, ledger + CLV; pregame windows at T-12 / T-3 / T-1 |
| `NCAAF Pipeline + Ledger` | Mon–Sat + Sunday settle + manual | College slate refresh / settle / site |
| `Deploy GitHub Pages` | Push to `main` touching `docs/` | Redeploy static site |

### Today's preseason slate (manual)

```bash
python scripts/run_today_slate.py --build-site --fresh-ledger
```

On GitHub: **Actions → NFL Pipeline + Ledger → Run workflow** → check **Today's slate only** and **Build site**.

Then open the **Games** tab on GitHub Pages to see each phase (EPA model, EV edges, money/ticket %, stage picks). The **CFB** tab shows the NCAAF board.

The public site shows **open plays**, **W–L record**, **unit PnL / bankroll**, and **weekly ledger**.

## Configuration

| Env var | Purpose |
|---|---|
| `ODDS_API_KEY` | The Odds API key (`regions=us,us2,eu` → Pinnacle + US retail); covers NFL + NCAAF |
| `ACTION_NETWORK_TOKEN` | Preferred Action Network Bearer JWT (takes precedence over cookie) |
| `ACTION_NETWORK_COOKIE` | Action Network Pro/EDGE session Cookie header (fallback) |
| `EV_THRESHOLD` | Minimum EV to flag (default `0.02`) |
| `MONEY_TICKET_GAP` | Handle % − ticket % confirmation (default `0.20`) |
| `PROP_EV_THRESHOLD` | Min EV for player props (default `0.02`) |
| `PREGAME_WINDOWS_HOURS` | Hours before kickoff to fire (default `12,3,1`) |
| `PREGAME_WINDOW_TOLERANCE_MINUTES` | Window match tolerance (default `25`) |
| `INACTIVE_PLAYERS` | Comma-separated names for target reallocation |

**Circa note:** The Odds API exposes Pinnacle reliably (`eu`). Circa is included in sharp preference order when the aggregator returns it; otherwise Pinnacle is the sharp benchmark.

## Action Network Pro / auth

Phase 4 uses Action Network public-betting splits (ticket % vs money %).

Many books already expose both percentages on the public scoreboard API (`markets.*.bet_info`). A logged-in **Pro/EDGE** Bearer token (preferred) or cookie can unlock more books / richer fields when AN gates them.

```bash
# Without auth (anonymous)
python scripts/diagnose_action_network.py

# NFL or NCAAF
python scripts/diagnose_action_network.py --league ncaaf

# With cookie pasted from browser
python scripts/diagnose_action_network.py --cookie 'YOUR_COOKIE_STRING'
```

**Grab the token / cookie**

1. Log into [actionnetwork.com](https://www.actionnetwork.com) with Pro/EDGE  
2. Open **NFL or NCAAF → Public Betting** and confirm money % is visible (not locked)  
3. DevTools → **Network** → click a `scoreboard` / `publicbetting` request  
4. Prefer **Authorization** bearer token → `ACTION_NETWORK_TOKEN` (or copy full **Cookie** → `ACTION_NETWORK_COOKIE`)  
5. Local: set in `.env`  
6. GitHub Actions: **Settings → Secrets → Actions →** matching secret names  

Tokens last longer than cookies; re-run `diagnose_action_network.py` when money % disappears.

`pro_splits_ready: true` means the Phase 4 money/ticket filter has the data it needs.

## Pipeline trigger logic

| Stage | Output | Action |
|---|---|---|
| 1 Ratings | Team off/def EPA power | Feed score generator |
| 2 Monte Carlo | `S_mod`, `T_mod`, `P_true` | Fair cover / win probs |
| 3 Market | `EV = P_true × decimal − 1` | Candidates with EV ≥ 2% and ≠ sharp consensus |
| 4 Filter | RLM **or** money/ticket gap ≥ 20% | Validated play / lean signal |
| Ledger | `data/ledger.json` / `data/ncaaf_ledger.json` | Deduped play history + settlement |
| Pages | `docs/` | Public board + NFL + CFB tabs |

## API

- `GET /api/health`
- `GET /api/signals` — full latest NFL payload
- `GET /api/plays` — validated NFL plays only
- `GET /api/ratings`
- `GET /api/splits` — split boards from latest NFL run
- `GET /api/stages` — stage picks + summary
- `POST /api/run?demo=true&skip_pbp=true` — trigger NFL pipeline
- `GET /api/ncaaf` — latest NCAAF payload (plays, stages, ratings)
- `POST /api/run-ncaaf?demo=true&skip_pbp=true` — trigger NCAAF pipeline

## Tests

```bash
pytest -q
```

## Disclaimer

For research / decision-support only. Does not place bets. Obey local law and sportsbook terms. Action Network endpoints are unofficial and may change or require a paid session.
