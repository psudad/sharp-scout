# Research (offline)

Not used by live NFL/NCAAF/NBA pipelines. Run from repo root:

```bash
python scripts/run_nba_paper_backtest.py
```

Outputs: `reports/nba_backtest_2026.csv`, `reports/nba_backtest_2026_report.md`, `reports/nba_backtest_2026_summary.json`.

Optional: `--fetch-2025-26` attempts a Yahoo scrape for the current season (slow; cached under `research/cache/`).
