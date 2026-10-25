#!/usr/bin/env python3
"""Settle NBA shadow paper ledger from ESPN final scores (no API keys)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba import paths as nba_paths  # noqa: E402
from sharp_scout.nba.report import write_paper_report  # noqa: E402
from sharp_scout.nba.settle import settle_nba_ledger  # noqa: E402
from sharp_scout.site.nba_page import build_nba_page  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Settle NBA paper ledger from ESPN")
    parser.add_argument("--build-page", action="store_true", help="Rebuild docs/nba.html")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    try:
        ledger = settle_nba_ledger()
    except Exception as exc:  # noqa: BLE001 — should not raise; guard for CI callers
        logger.error("NBA settle aborted: %s", exc)
        return 1

    try:
        write_paper_report(ledger, nba_paths.NBA_REPORT_PATH)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NBA paper report write failed: %s", exc)

    if args.build_page:
        try:
            build_nba_page()
        except Exception as exc:  # noqa: BLE001
            logger.warning("NBA page build failed: %s", exc)

    plays = ledger.get("plays") or []
    settled = sum(1 for p in plays if p.get("settled_at"))
    print(f"NBA ledger: {len(plays)} plays, {settled} with settled_at")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
