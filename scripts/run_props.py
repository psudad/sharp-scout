#!/usr/bin/env python3
"""Run player props pipeline only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.props.pipeline import run_props_pipeline  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Sharp Scout player props pipeline")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--skip-pbp", action="store_true")
    p.add_argument("--build-site", action="store_true")
    p.add_argument("--no-ledger", action="store_true")
    p.add_argument("--season", type=int, default=None)
    p.add_argument("--week", type=int, default=None)
    args = p.parse_args()
    result = run_props_pipeline(
        demo=args.demo,
        skip_pbp=args.skip_pbp or args.demo,
        update_ledger=not args.no_ledger,
        build_pages=args.build_site,
        season=args.season,
        week=args.week,
    )
    print(
        json.dumps(
            {
                "generated_at": result["generated_at"],
                "demo": result["demo"],
                "n_events": result["n_events"],
                "n_validated": result["n_validated"],
                "plays": [
                    {
                        "player": s.get("player_name"),
                        "market": s["market"],
                        "side": s["side"],
                        "line": s["line"],
                        "book": s["book"],
                        "edge": s["edge"],
                        "tier": s["tier"],
                        "alt": s.get("is_alternate"),
                    }
                    for s in result["plays"][:20]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
