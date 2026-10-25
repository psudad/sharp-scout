#!/usr/bin/env python3
"""Settle NBA shadow paper ledger from ESPN final scores (no API keys)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba import paths as nba_paths  # noqa: E402
from sharp_scout.nba.report import write_paper_report  # noqa: E402
from sharp_scout.nba.settle import settle_nba_ledger  # noqa: E402
from sharp_scout.site.nba_page import build_nba_page  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Settle NBA paper ledger from ESPN")
    parser.add_argument("--build-page", action="store_true", help="Rebuild docs/nba.html")
    args = parser.parse_args()
    ledger = settle_nba_ledger()
    write_paper_report(ledger, nba_paths.NBA_REPORT_PATH)
    if args.build_page:
        build_nba_page()
    settled = sum(1 for p in ledger.get("plays") or [] if p.get("settled_at"))
    print(f"NBA ledger: {len(ledger.get('plays') or [])} plays, {settled} with settled_at")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
