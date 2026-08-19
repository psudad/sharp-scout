# AGENTS.md

## Cursor Cloud specific instructions

Sharp Scout is a single Python 3.12 package (`src/sharp_scout`, installed editable as `sharp-scout`) that produces NFL and NCAA football betting **signals** — a 4-phase pipeline (ratings → Monte Carlo → market EV → split filter), a player-props engine, a static GitHub Pages site builder under `docs/`, and an optional FastAPI server. There is no separate frontend build; `index.html` / `docs/index.html` are static and served/generated directly. NCAAF reuses the same phases with cfbfastR PBP, Odds API `americanfootball_ncaaf`, Action Network `ncaaf`, and `data/ncaaf_ledger.json`.

### Environment
- Dependencies are installed into a virtualenv at `.venv` by the update script (`pip install -e ".[dev]"`). Activate it with `source .venv/bin/activate` before running anything.
- No system services (DB/queue/etc.) are required. Persistence is local SQLite (`data/sharp_scout.db`) and JSON files; these are created automatically.

### Run / test / build (all from repo root, venv active)
- Tests: `pytest -q` (see `README.md`). Fully offline; no keys needed.
- Pipeline (NFL sides): `python scripts/run_pipeline.py --demo --build-site`
- Pipeline (NCAAF): `python scripts/run_ncaaf.py --demo --build-site`
- Props: `python scripts/run_props.py --demo --build-site`
- API dev server: `uvicorn sharp_scout.api.main:app --host 0.0.0.0 --port 8000 --reload` then hit `GET /api/health`, `POST /api/run?demo=true`, `GET /api/plays`, `GET /api/ncaaf`, `POST /api/run-ncaaf?demo=true`, `GET /` (dashboard UI).
- There is no configured linter (no ruff/flake8 config despite `.ruff_cache` in `.gitignore`); "lint" is not a separate step here.

### Non-obvious caveats
- **Always use `--demo` (and/or `--skip-pbp`) without real API keys.** Live mode requires `ODDS_API_KEY` (The Odds API) and optionally `ACTION_NETWORK_COOKIE`; without them a live run has no market data. `--demo` uses mock odds/splits and neutral ratings so the full pipeline runs offline.
- **Demo runs mutate git-tracked files**: `data/ledger.json`, `data/ncaaf_ledger.json`, and `docs/` (site + ledger + record) are rewritten and appended each run. After demo/testing, run `git checkout -- data/ledger.json data/ncaaf_ledger.json docs/` to avoid committing generated demo data.
- In NFL demo mode only the `KC@BUF` matchup is populated, so the Ratings tab shows `0.000` for all other teams and the dashboard "Log" tab notes a missing Action Network cookie — both are expected, not bugs. NCAAF demo only populates `ALA@UGA`.
- Copy `.env.example` to `.env` for local live runs; env vars are read via `pydantic-settings`.
