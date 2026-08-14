# Sharp Scout

Institutional-grade **NFL betting signal pipeline** (signals only — no auto-betting).

Architecture runs bottom-up first so market data filters model edges instead of biasing the baseline:

1. **Fundamental engine** — opponent-adjusted EPA / success / YPP power ratings (nflverse play-by-play parquet)
2. **Monte Carlo** — correlated score simulations → model spread/total and `P_true`
3. **Market model** — Pinnacle (and Circa when present) no-vig odds via [The Odds API](https://the-odds-api.com) → EV
4. **Split filter** — Action Network ticket/money % + reverse line movement confirmation

Validated plays are stored in [`data/ledger.json`](data/ledger.json) and published to **GitHub Pages** under [`docs/`](docs/).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Add ODDS_API_KEY (required for live odds)
# Optional: ACTION_NETWORK_COOKIE (Pro/EDGE session) for richer splits
python scripts/diagnose_action_network.py   # verify money/ticket %

# Demo run + rebuild Pages site
python scripts/run_pipeline.py --demo --build-site

# Live run
python scripts/run_pipeline.py --build-site

# Preseason / manual pasted odds (The Odds API has no preseason) + live Action Network splits
python scripts/run_manual_slate.py data/manual_slate.example.json --date 20260814 --skip-pbp --build-site

# Settle completed games (nflverse scores) and refresh site
python scripts/settle_plays.py --build-site
# Or one game manually:
python scripts/settle_plays.py --manual KC BUF 24 20 --build-site

# Local API (optional)
uvicorn sharp_scout.api.main:app --host 0.0.0.0 --port 8000
```

## Stage picks (compare every lens)

For each game the pipeline also picks a side from **each data stage** independently:

| Stage | Winner rule |
|---|---|
| `model` | Monte Carlo / fundamental favorite |
| `sharp` | Pinnacle/Circa no-vig favorite |
| `public` | Ticket-% majority |
| `money` | Handle-% majority |
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

## Pregame schedule (T-12h / T-3h / T-1h)

`scripts/run_pregame.py` checks upcoming kickoffs and fires **sides + props** when a game is within ±25 minutes of 12h, 3h, or 1h before kickoff. Fired windows are recorded in `data/schedule_state.json` so each window runs once.

GitHub Action **Pregame Windows** runs every 30 minutes on `main`.

```bash
python scripts/run_pregame.py --demo
```

## GitHub Pages (weekly public board)

### One-time repo setup

1. **Settings → Pages → Build and deployment**
   - Source: **GitHub Actions**
2. **Settings → Secrets and variables → Actions** — add:
   - `ODDS_API_KEY` (required for live odds)
   - `ACTION_NETWORK_COOKIE` (optional; money/handle %)
3. Merge this branch to `main`, then run **Actions → NFL Pipeline + Ledger → Run workflow**
4. Site URL: `https://<user>.github.io/sharp-scout/`

### What runs automatically

| Workflow | When | Does |
|---|---|---|
| `Pregame Windows` | Every 30 min | Fire T-12h / T-3h / T-1h side+prop runs for due games → update ledger + Pages |
| `NFL Pipeline + Ledger` | Tue / Thu / Sun–Mon + manual | Full slate refresh / settle / site |
| `Deploy GitHub Pages` | Push to `main` touching `docs/` | Redeploy static site |

The public site shows **open plays**, **W–L record**, **unit PnL / bankroll**, and **weekly ledger**.

## Configuration

| Env var | Purpose |
|---|---|
| `ODDS_API_KEY` | The Odds API key (`regions=us,us2,eu` → Pinnacle + US retail) |
| `ACTION_NETWORK_COOKIE` | Action Network Pro/EDGE session Cookie header (see below) |
| `EV_THRESHOLD` | Minimum EV to flag (default `0.02`) |
| `MONEY_TICKET_GAP` | Handle % − ticket % confirmation (default `0.20`) |
| `PROP_EV_THRESHOLD` | Min EV for player props (default `0.02`) |
| `PREGAME_WINDOWS_HOURS` | Hours before kickoff to fire (default `12,3,1`) |
| `PREGAME_WINDOW_TOLERANCE_MINUTES` | Window match tolerance (default `25`) |
| `INACTIVE_PLAYERS` | Comma-separated names for target reallocation |

**Circa note:** The Odds API exposes Pinnacle reliably (`eu`). Circa is included in sharp preference order when the aggregator returns it; otherwise Pinnacle is the sharp benchmark.

## Action Network Pro / cookie

Phase 4 uses Action Network public-betting splits (ticket % vs money %).

Many books already expose both percentages on the public scoreboard API (`markets.*.bet_info`). A logged-in **Pro/EDGE** cookie can unlock more books / richer fields when AN gates them.

```bash
# Without cookie (anonymous)
python scripts/diagnose_action_network.py

# With cookie pasted from browser
python scripts/diagnose_action_network.py --cookie 'YOUR_COOKIE_STRING'
```

**Grab the cookie**

1. Log into [actionnetwork.com](https://www.actionnetwork.com) with Pro/EDGE  
2. Open **NFL → Public Betting** and confirm money % is visible (not locked)  
3. DevTools → **Network** → click a `scoreboard` / `api.actionnetwork.com` request  
4. Request Headers → copy the full **Cookie** value  
5. Local: set `ACTION_NETWORK_COOKIE=...` in `.env`  
6. GitHub Actions: **Settings → Secrets → Actions →** `ACTION_NETWORK_COOKIE`  

Cookies expire (often days–weeks). Re-run `diagnose_action_network.py` when money % disappears; refresh the secret when needed.

`pro_splits_ready: true` means the Phase 4 money/ticket filter has the data it needs.

## Pipeline trigger logic

| Stage | Output | Action |
|---|---|---|
| 1 Ratings | Team off/def EPA power | Feed score generator |
| 2 Monte Carlo | `S_mod`, `T_mod`, `P_true` | Fair cover / win probs |
| 3 Market | `EV = P_true × decimal − 1` | Candidates with EV ≥ 2% and ≠ sharp consensus |
| 4 Filter | RLM **or** money/ticket gap ≥ 20% | Validated play / lean signal |
| Ledger | `data/ledger.json` | Deduped play history + settlement |
| Pages | `docs/` | Public board + record |

## API

- `GET /api/health`
- `GET /api/signals` — full latest payload
- `GET /api/plays` — validated plays only
- `GET /api/ratings`
- `POST /api/run?demo=true&skip_pbp=true` — trigger pipeline

## Tests

```bash
pytest -q
```

## Disclaimer

For research / decision-support only. Does not place bets. Obey local law and sportsbook terms. Action Network endpoints are unofficial and may change or require a paid session.
