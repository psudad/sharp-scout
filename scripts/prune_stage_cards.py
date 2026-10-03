#!/usr/bin/env python3
"""Remove pending stage cards outside the current display slate (NFL or NCAAF)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.ledger.tracker import (  # noqa: E402
    compute_record,
    ledger_sport_from_path,
    load_ledger,
    prune_stage_cards_outside_display_slate,
    save_ledger,
)
from sharp_scout.site.build import build_site  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Prune far-future pending stage cards from ledgers")
    p.add_argument("--sport", choices=["nfl", "ncaaf", "both"], default="both")
    p.add_argument("--build-site", action="store_true")
    args = p.parse_args()

    sports = ["nfl", "ncaaf"] if args.sport == "both" else [args.sport]
    for key in sports:
        path = DATA_DIR / ("ncaaf_ledger.json" if key == "ncaaf" else "ledger.json")
        if not path.exists():
            continue
        ledger = load_ledger(path)
        before = len(ledger.get("stage_cards") or [])
        pruned = prune_stage_cards_outside_display_slate(
            ledger, sport=ledger_sport_from_path(path)
        )
        record = compute_record(ledger, path=path)
        save_ledger(ledger, path)
        print(
            json.dumps(
                {
                    "sport": key,
                    "stage_cards_before": before,
                    "pruned_pending": pruned,
                    "stage_cards_after": len(ledger.get("stage_cards") or []),
                    "stage_pending_model": (record.get("stage_records") or {})
                    .get("model", {})
                    .get("pending"),
                },
                indent=2,
            )
        )

    if args.build_site:
        build_site()
        print("Rebuilt docs/")


if __name__ == "__main__":
    main()
