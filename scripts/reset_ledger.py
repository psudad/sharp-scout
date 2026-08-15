#!/usr/bin/env python3
"""Reset ledger to remove demo noise; optionally keep live plays from a cutoff date."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.ledger.tracker import compute_record, empty_ledger, save_ledger  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Reset Sharp Scout ledger")
    p.add_argument(
        "--keep-since",
        default=None,
        help="Keep non-demo plays created on/after this UTC date (YYYY-MM-DD)",
    )
    p.add_argument(
        "--from-ledger",
        type=Path,
        default=ROOT / "data" / "ledger.json",
        help="Source ledger to filter (default: data/ledger.json)",
    )
    args = p.parse_args()

    src = json.loads(args.from_ledger.read_text())
    keep_since = args.keep_since

    kept = []
    for play in src.get("plays") or []:
        if play.get("event_id") == "demo-kc-buf":
            continue
        if play.get("player_name") and play.get("event_id") == "demo-kc-buf":
            continue
        # Drop orphaned demo props (no real event_id / team context)
        if play.get("play_type") == "prop" and not play.get("away_team"):
            continue
        if keep_since:
            created = (play.get("created_at") or "")[:10]
            if created < keep_since:
                continue
        play = dict(play)
        play["status"] = "pending"
        play["home_score"] = None
        play["away_score"] = None
        play["prop_result"] = None
        play["pnl_units"] = None
        play["settled_at"] = None
        kept.append(play)

    ledger = empty_ledger()
    ledger["plays"] = kept
    ledger["stage_cards"] = [
        c for c in (src.get("stage_cards") or []) if c.get("event_id") != "demo-kc-buf"
    ]
    save_ledger(ledger)
    record = compute_record()
    print(
        json.dumps(
            {
                "ok": True,
                "kept_plays": len(kept),
                "record": record,
                "keep_since": keep_since,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
