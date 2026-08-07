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
# Optional: ACTION_NETWORK_COOKIE for money/% handle splits

# Demo run + rebuild Pages site
python scripts/run_pipeline.py --demo --build-site

# Live run
python scripts/run_pipeline.py --build-site

# Settle completed games (nflverse scores) and refresh site
python scripts/settle_plays.py --build-site
# Or one game manually:
python scripts/settle_plays.py --manual KC BUF 24 20 --build-site

# Local API (optional)
uvicorn sharp_scout.api.main:app --host 0.0.0.0 --port 8000
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
| `NFL Pipeline + Ledger` | Tue / Thu / Sun–Mon schedule + manual | Settle prior plays → run pipeline → update `data/ledger.json` + `docs/` → deploy Pages |
| `Deploy GitHub Pages` | Push to `main` touching `docs/` | Redeploy static site |

The public site shows **open plays**, **W–L record**, **unit PnL / bankroll**, and **weekly ledger**.

## Configuration

| Env var | Purpose |
|---|---|
| `ODDS_API_KEY` | The Odds API key (`regions=us,us2,eu` → Pinnacle + US retail) |
| `ACTION_NETWORK_COOKIE` | Browser session cookie for money/handle % (ticket % often public) |
| `EV_THRESHOLD` | Minimum EV to flag (default `0.02`) |
| `MONEY_TICKET_GAP` | Handle % − ticket % confirmation (default `0.20`) |
| `MONTE_CARLO_SIMS` | Sims per game (default `10000`) |

**Circa note:** The Odds API exposes Pinnacle reliably (`eu`). Circa is included in sharp preference order when the aggregator returns it; otherwise Pinnacle is the sharp benchmark.

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
