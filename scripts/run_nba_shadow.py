#!/usr/bin/env python3
"""Run the private NBA shadow pipeline (game lines + props).

Shadow data lives under data/shadow/. CI rebuilds docs/nba.html only (see nba-shadow.yml).
"""

from __future__ import annotations

import argparse
import json
import sys

from sharp_scout.config import get_settings
from sharp_scout.nba.pipeline import run_nba_shadow
from sharp_scout.utils.odds import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="NBA shadow / paper-trading scan")
    parser.add_argument("--demo", action="store_true", help="Offline fixture (no Odds API credits)")
    parser.add_argument("--no-props", action="store_true", help="Game lines only")
    parser.add_argument("--no-ledger", action="store_true", help="Scan only; do not append ledger")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    setup_logging(args.log_level)
    settings = get_settings()
    fetch_props = not args.no_props and settings.nba_props_scan_enabled
    payload = run_nba_shadow(
        demo=args.demo,
        fetch_props=fetch_props,
        append_ledger=not args.no_ledger,
    )
    print(json.dumps({k: payload[k] for k in payload if k != "signals"}, indent=2))
    print(f"signals: {len(payload.get('signals') or [])}")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
