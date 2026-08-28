#!/usr/bin/env python3
"""Reset Sharp Scout ledger(s) to a clean empty state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.ledger.tracker import compute_record, empty_ledger, save_ledger  # noqa: E402
from sharp_scout.sports import get_sport  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Reset Sharp Scout ledger")
    p.add_argument(
        "--sport",
        choices=["nfl", "ncaaf", "all"],
        default="all",
        help="Which ledger to reset (default: all)",
    )
    p.add_argument(
        "--keep-since",
        default=None,
        help="Legacy NFL filter: keep plays created on/after UTC date (YYYY-MM-DD)",
    )
    args = p.parse_args()

    targets: list[tuple[str, Path]] = []
    if args.sport in ("nfl", "all"):
        targets.append(("nfl", DATA_DIR / "ledger.json"))
    if args.sport in ("ncaaf", "all"):
        targets.append(("ncaaf", DATA_DIR / get_sport("ncaaf").ledger_name))

    results = {}
    for name, path in targets:
        if name == "nfl" and args.keep_since and path.exists():
            src = json.loads(path.read_text())
            kept = []
            for play in src.get("plays") or []:
                if play.get("event_id") == "demo-kc-buf":
                    continue
                created = (play.get("created_at") or "")[:10]
                if created < args.keep_since:
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
        else:
            ledger = empty_ledger()
        save_ledger(ledger, path=path)
        results[name] = {"path": str(path), "record": compute_record(ledger)}

    print(json.dumps({"ok": True, "reset": results}, indent=2))


if __name__ == "__main__":
    main()
