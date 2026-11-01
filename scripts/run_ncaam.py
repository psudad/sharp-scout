#!/usr/bin/env python3
"""NCAAM blended model runner — lock picks and publish College Basketball board."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.ncaam.lock import LEDGER_PATH  # noqa: E402
from sharp_scout.ncaam.runner import run_loop, run_pass  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NCAAM lock pipeline")
    parser.add_argument("--loop", action="store_true", help="Loop until budget or slate done")
    parser.add_argument("--once", action="store_true", help="Single pass (default)")
    parser.add_argument("--demo", action="store_true", help="Offline fixtures; do not touch live ledger")
    parser.add_argument("--pass-every-min", type=int, default=15)
    parser.add_argument("--budget-min", type=int, default=340)
    parser.add_argument("--commit", action="store_true", help="Git commit after locks (live only)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    ledger_path = LEDGER_PATH
    if args.demo:
        tmp = Path(tempfile.mkdtemp(prefix="ncaam_demo_"))
        ledger_path = tmp / "ncaam_ledger.json"
        ledger_path.write_text(
            '{"updated_at":"1970-01-01T00:00:00+00:00","starting_units":100,"plays":[],"stage_cards":[],"disagreements":[]}\n'
        )

    if args.loop and not args.demo:
        return run_loop(
            demo=False,
            pass_every_min=args.pass_every_min,
            budget_min=args.budget_min,
        )
    if args.loop and args.demo:
        return run_loop(demo=True, pass_every_min=1, budget_min=1)

    summary = run_pass(demo=args.demo, ledger_path=ledger_path, commit=args.commit and not args.demo)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
