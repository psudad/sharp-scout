#!/usr/bin/env python3
"""Settle NCAAM ledger from ESPN finals."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.ncaam.settle import settle_ncaam_ledger  # noqa: E402
from sharp_scout.site.ncaam_page import build_ncaam_page  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-page", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    ledger = settle_ncaam_ledger()
    if args.build_page:
        build_ncaam_page()
    print(f"NCAAM plays: {len(ledger.get('plays') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
