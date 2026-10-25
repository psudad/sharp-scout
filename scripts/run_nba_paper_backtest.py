#!/usr/bin/env python3
"""Research: backtest NBA shadow game-line model on free Yahoo MGM closing odds."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.research.nba_paper_backtest import (  # noqa: E402
    YAHOO_SEASON_FILES,
    build_score_index,
    load_yahoo_seasons,
    render_markdown,
    run_game_line_backtest,
    summarize_backtest,
    write_csv,
)
from sharp_scout.utils.odds import setup_logging

REPORTS = ROOT / "reports"


def _maybe_fetch_2025_26(cache_dir: Path) -> Path | None:
    """Optional Yahoo scrape for 2025-26 (slow; cached JSON → CSV)."""
    out_csv = cache_dir / "odds_2025_26.csv"
    if out_csv.exists() and out_csv.stat().st_size > 1000:
        return out_csv
    try:
        import pandas as pd
    except ImportError:
        return None
    scrape_root = cache_dir / "scrape_yahoo_odds"
    if not (scrape_root / "scrape_yahoo_nba.py").exists():
        import subprocess

        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/csdurfee/scrape_yahoo_odds.git",
                str(scrape_root),
            ],
            check=False,
            capture_output=True,
        )
    if not (scrape_root / "scrape_yahoo_nba.py").exists():
        return None
    sys.path.insert(0, str(scrape_root))
    try:
        from scrape_yahoo_nba import ScrapeYahooNBA  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logging.warning("2025-26 Yahoo scrape unavailable: %s", exc)
        return None

    import datetime as dt

    scraper = ScrapeYahooNBA()
    fetch_dir = cache_dir / "yahoo_json_2025"
    fetch_dir.mkdir(parents=True, exist_ok=True)
    start = dt.datetime(2025, 10, 21, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 10, 25, tzinfo=dt.timezone.utc)
    try:
        scraper.fetch_yahoo_data(str(fetch_dir), start=start.replace(tzinfo=None), end=end.replace(tzinfo=None))
        df = scraper.parse_all_games(str(fetch_dir))
        if df is not None and len(df):
            df.to_csv(out_csv, index=False)
            return out_csv
    except Exception as exc:  # noqa: BLE001
        logging.warning("2025-26 scrape failed: %s", exc)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="NBA paper model research backtest")
    parser.add_argument("--fetch-2025-26", action="store_true", help="Attempt Yahoo scrape for 2025-26")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    setup_logging(args.log_level)

    cache = ROOT / "research" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    extra: list[Path] = []
    if args.fetch_2025_26:
        p = _maybe_fetch_2025_26(cache)
        if p:
            extra.append(p)

    seasons = list(YAHOO_SEASON_FILES.keys())
    if extra:
        seasons.append("2025-26")
    from sharp_scout.research.nba_paper_backtest import load_sbr_archive

    sbr_path = cache / "nba_archive_10Y.json"
    if not sbr_path.exists():
        import subprocess

        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/flancast90/sportsbookreview-scraper.git",
                str(cache / "sbr-scraper"),
            ],
            check=False,
            capture_output=True,
        )
        src = cache / "sbr-scraper" / "data" / "nba_archive_10Y.json"
        if src.exists():
            sbr_path.write_bytes(src.read_bytes())

    rows = load_sbr_archive(sbr_path)
    rows.extend(load_yahoo_seasons(seasons=[s for s in seasons if s != "2025-26"], extra_csv_paths=extra))
    n_sbr = len(load_sbr_archive(sbr_path))
    logging.info("Loaded %d game rows (SBR pre-2021: %d, Yahoo 2021+)", len(rows), n_sbr)

    score_index = build_score_index(lookback_days=450)
    result = run_game_line_backtest(rows, score_index=score_index)
    summary = summarize_backtest(result)

    csv_path = REPORTS / "nba_backtest_2026.csv"
    md_path = REPORTS / "nba_backtest_2026_report.md"
    json_path = REPORTS / "nba_backtest_2026_summary.json"
    write_csv(csv_path, result.bets)
    md_path.write_text(
        render_markdown(
            summary,
            title="NBA shadow game-line backtest (2021–22 through 2025–26, closing MGM/Yahoo)",
        )
    )
    json_path.write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps({k: summary[k] for k in ("picks", "possible", "every_game", "by_market")}, indent=2))
    print(f"Wrote {csv_path}, {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
