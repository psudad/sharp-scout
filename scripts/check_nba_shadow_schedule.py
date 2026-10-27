#!/usr/bin/env python3
"""CI gate: scheduled NBA shadow runs match the seasonal cron for the intended ET slot."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba.schedule_guard import scheduled_cron_run_allowed  # noqa: E402
from sharp_scout.scheduler.odds_credit_pause import scheduled_odds_pause_active  # noqa: E402


def main() -> None:
    now = datetime.now(timezone.utc)
    cron = os.environ.get("GITHUB_SCHEDULE_CRON", "").strip()
    ok = bool(cron) and scheduled_cron_run_allowed(cron, now)
    skip_props = ok and scheduled_odds_pause_active(now)
    if ok:
        msg = f"Allowed scheduled run: cron={cron!r} now={now.isoformat()}"
        if skip_props:
            msg += " (game lines only — props paused until 2026-11-05 ET)"
        print(msg)
    else:
        print(
            f"Skipping scheduled run: cron={cron!r} now={now.isoformat()} "
            "(wrong seasonal line, outside late window, or unknown cron)"
        )

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if ok else 'false'}\n")
            fh.write(f"skip_props={'true' if skip_props else 'false'}\n")


if __name__ == "__main__":
    main()
