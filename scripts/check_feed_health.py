#!/usr/bin/env python3
"""Exit non-zero when data/health/feeds.json reports a missing critical feed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEEDS = ROOT / "data" / "health" / "feeds.json"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sport", default="nfl", choices=["nfl", "ncaaf", "ncaam"])
    p.add_argument("--path", type=Path, default=FEEDS)
    args = p.parse_args()
    from sharp_scout.health.feeds import critical_feed_ids_for_sport, load_feeds_file

    data = load_feeds_file(args.path)
    if not data:
        print(f"feed health file missing: {args.path}", file=sys.stderr)
        sys.exit(1)
    critical = critical_feed_ids_for_sport(args.sport)
    by_id = {row.get("id"): row for row in data.get("feeds") or []}
    failed: list[str] = []
    for fid in sorted(critical):
        row = by_id.get(fid)
        if not row or row.get("status") == "missing":
            failed.append(fid)
            print(f"MISSING {fid}: {row.get('reason') if row else 'never checked'}", file=sys.stderr)
    if failed:
        sys.exit(1)
    print(f"feed health ok for {args.sport} ({len(critical)} critical feeds)")
    sys.exit(0)


if __name__ == "__main__":
    main()