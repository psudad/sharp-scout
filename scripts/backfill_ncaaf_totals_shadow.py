#!/usr/bin/env python3
"""Backfill NCAAF high-EV totals shadow ledger from git signal snapshots, then grade."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.ncaaf.shadow.backfill import backfill_from_git_history  # noqa: E402
from sharp_scout.ncaaf.shadow.report import write_summary_and_report  # noqa: E402
from sharp_scout.ncaaf.shadow.settle import settle_shadow_ledger  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill NCAAF totals high-EV shadow ledger")
    p.add_argument(
        "--signals-path",
        default="docs/latest_ncaaf_signals.json",
        help="Git-tracked NCAAF signals snapshot path",
    )
    args = p.parse_args()

    backfill = backfill_from_git_history(args.signals_path, repo_root=ROOT)
    settle = settle_shadow_ledger()
    summary = write_summary_and_report()
    out = {"backfill": backfill, "settle": settle, "summary": summary}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
