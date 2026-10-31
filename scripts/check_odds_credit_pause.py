#!/usr/bin/env python3
"""CI gate for scheduled Odds API workflows during billing/credit pauses."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.scheduler.odds_credit_pause import (  # noqa: E402
    ODDS_CREDIT_RESUME_ET_DATE,
    pregame_scheduled_allowed,
    scheduled_odds_pause_active,
    workflow_scheduled_allowed_during_pause,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--workflow",
        required=True,
        choices=("pregame", "props", "ncaaf-lines", "ncaaf-staleness"),
    )
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    cron = os.environ.get("GITHUB_SCHEDULE_CRON", "").strip()
    event = os.environ.get("GITHUB_EVENT_NAME", "schedule").strip()

    if event == "workflow_dispatch":
        proceed, nov1 = True, False
    elif args.workflow == "pregame":
        proceed, nov1 = pregame_scheduled_allowed(cron, now)
    elif scheduled_odds_pause_active(now):
        proceed = workflow_scheduled_allowed_during_pause(args.workflow)
        nov1 = False
    else:
        proceed, nov1 = True, False

    if proceed and nov1:
        print(f"Pregame Nov 1 2026 NFL-only exception (cron={cron!r})")
    elif proceed:
        print(f"Scheduled {args.workflow} allowed at {now.isoformat()}")
    else:
        print(
            f"Skipping scheduled {args.workflow}: Odds credit pause until "
            f"{ODDS_CREDIT_RESUME_ET_DATE.isoformat()} ET (cron={cron!r})"
        )

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"proceed={'true' if proceed else 'false'}\n")
            fh.write(f"nov1_nfl_only={'true' if nov1 else 'false'}\n")


if __name__ == "__main__":
    main()
