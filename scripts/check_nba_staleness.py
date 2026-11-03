#!/usr/bin/env python3
"""NBA staleness guard: fail (exit 1) when a game day has no scan by the expected time.

No Odds API calls. Reads data/shadow/nba_latest_signals.json and the paper store, and
ESPN's public scoreboard for today's first tip-off.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba.schedule_guard import (  # noqa: E402
    ET,
    latest_live_scan_utc,
    nba_scan_stale,
    scan_fresh_for_et_date,
)


def main() -> int:
    now = datetime.now(timezone.utc)
    try:
        from sharp_scout.data.espn_nba import fetch_espn_nba_first_tip_utc

        first_tip = fetch_espn_nba_first_tip_utc(now.astimezone(ET).date())
    except Exception as exc:  # noqa: BLE001
        print(f"First tip-off lookup failed ({exc}); cannot tell if today is a game day")
        first_tip = None
    last = latest_live_scan_utc()
    fresh = scan_fresh_for_et_date(now.astimezone(ET).date(), last_scan_utc=last)
    stale, why = nba_scan_stale(now, first_tip_utc=first_tip, scan_fresh=fresh)
    last_s = last.astimezone(ET).isoformat() if last else "none"
    tip_s = first_tip.astimezone(ET).isoformat() if first_tip else "none"
    print(f"NBA staleness: last live scan {last_s} ET, first tip {tip_s} ET -> {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"stale={'true' if stale else 'false'}\n")
    if stale:
        print("::error title=NBA data is stale::" + why)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
