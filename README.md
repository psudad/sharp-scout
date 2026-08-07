# Sharp Scout

Institutional-grade **NFL betting signal pipeline** (signals only — no auto-betting).

Architecture runs bottom-up first so market data filters model edges instead of biasing the baseline:

1. **Fundamental engine** — opponent-adjusted EPA / success / YPP power ratings (nflverse play-by-play parquet)
2. **Monte Carlo** — correlated score simulations → model spread/total and `P_true`
3. **Market model** — Pinnacle (and Circa when present) no-vig odds via [The Odds API](https://the-odds-api.com) → EV
4. **Split filter** — Action Network ticket/money % + reverse line movement confirmation

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Add ODDS_API_KEY (required for live odds)
# Optional: ACTION_NETWORK_COOKIE for money/% handle splits

# Demo run (mock odds + splits, no keys)
python scripts/run_pipeline.py --demo

# Live run
python scripts/run_pipeline.py

# API + dashboard
uvicorn sharp_scout.api.main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

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

Artifacts land in `artifacts/latest_signals.json`. SQLite history: `data/sharp_scout.db`.

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
