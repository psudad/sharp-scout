#!/usr/bin/env python3
"""Run QA gate on pipeline output and ledger plays.

Layer 1 blocks deploy on demo/stale ratings.
Layer 2 quarantines or voids implausible pending plays.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.qa.gate import apply_qa_gate  # noqa: E402
from sharp_scout.site.build import build_site  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Sharp Scout QA gate")
    p.add_argument("--sport", choices=["nfl", "ncaaf", "both"], default="both")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Review only — do not update ledger statuses",
    )
    p.add_argument(
        "--allow-demo",
        action="store_true",
        help="Allow demo-mode signals (local testing only)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if Layer 1 fails (blocks CI deploy)",
    )
    p.add_argument(
        "--build-site",
        action="store_true",
        help="Rebuild docs/ after applying QA actions",
    )
    args = p.parse_args()

    sports = ["nfl", "ncaaf"] if args.sport == "both" else [args.sport]
    results = []
    exit_code = 0

    for sport in sports:
        result = apply_qa_gate(
            sport,
            apply=not args.dry_run,
            allow_demo=args.allow_demo,
        )
        results.append(result.summary())
        if args.strict and result.block_deploy:
            exit_code = 1

    print(json.dumps(results if len(results) > 1 else results[0], indent=2))

    if args.build_site and not args.dry_run:
        out = build_site()
        print(f"Built site → {out}", file=sys.stderr)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
