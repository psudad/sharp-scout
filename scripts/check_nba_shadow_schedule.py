#!/usr/bin/env python3
"""CI gate: scheduled NBA shadow runs match the seasonal cron for the intended ET slot."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba.schedule_guard import (  # noqa: E402
    intended_et_date_from_cron,
    is_backup_cron,
    primary_scan_satisfied_for_et_date,
    scheduled_cron_run_allowed,
)
from sharp_scout.scheduler.odds_credit_pause import scheduled_odds_pause_active  # noqa: E402


def main() -> None:
    now = datetime.now(timezone.utc)
    cron = os.environ.get("GITHUB_SCHEDULE_CRON", "").strip()
    ok = bool(cron) and scheduled_cron_run_allowed(cron, now)
    skip_props = ok and scheduled_odds_pause_active(now)

    if ok and is_backup_cron(cron):
        et_day = intended_et_date_from_cron(cron, now)
        if et_day is not None and primary_scan_satisfied_for_et_date(et_day):
            print(
                f"Skipping backup run: primary scan already recorded for {et_day.isoformat()} ET "
                f"(cron={cron!r})"
            )
            ok = False

    if ok:
        msg = f"Allowed scheduled run: cron={cron!r} now={now.isoformat()}"
        if skip_props:
            msg += " (game lines only — props paused until 2026-11-06 ET)"
        print(msg)
    else:
        print(
            f"Skipping scheduled run: cron={cron!r} now={now.isoformat()} "
            "(wrong seasonal line, outside late window, backup unnecessary, or unknown cron)"
        )

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if ok else 'false'}\n")
            fh.write(f"skip_props={'true' if skip_props else 'false'}\n")


if __name__ == "__main__":
    main()
