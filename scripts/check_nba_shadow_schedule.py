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
    ET,
    intended_et_date_from_cron,
    is_backup_cron,
    primary_scan_satisfied_for_et_date,
    scheduled_cron_run_allowed,
)
from sharp_scout.scheduler.odds_credit_pause import (  # noqa: E402
    ODDS_CREDIT_RESUME_ET_DATE,
    scheduled_odds_pause_active,
)


def _first_tip_utc(now: datetime) -> datetime | None:
    """First NBA tip-off of today's ET slate (ESPN, no Odds API). None if unknown."""
    try:
        from sharp_scout.data.espn_nba import fetch_espn_nba_first_tip_utc

        return fetch_espn_nba_first_tip_utc(now.astimezone(ET).date())
    except Exception as exc:  # noqa: BLE001
        print(f"First tip-off lookup failed ({exc}); using fixed late-start limit")
        return None


def main() -> None:
    now = datetime.now(timezone.utc)
    cron = os.environ.get("GITHUB_SCHEDULE_CRON", "").strip()
    first_tip = _first_tip_utc(now) if cron else None
    if first_tip is not None:
        print(f"First tip-off today: {first_tip.astimezone(ET).isoformat()} ET")
    else:
        print("First tip-off unknown; late starts limited to the fixed window")
    ok = bool(cron) and scheduled_cron_run_allowed(cron, now, first_tip_utc=first_tip)
    skip_props = ok and scheduled_odds_pause_active(now)

    if ok and is_backup_cron(cron):
        et_day = intended_et_date_from_cron(cron, now, first_tip_utc=first_tip)
        if et_day is not None and primary_scan_satisfied_for_et_date(et_day):
            print(
                f"Skipping backup run: primary scan already recorded for {et_day.isoformat()} ET "
                f"(cron={cron!r})"
            )
            ok = False

    if ok:
        msg = f"Allowed scheduled run: cron={cron!r} now={now.isoformat()}"
        if skip_props:
            msg += f" (game lines only — props paused until {ODDS_CREDIT_RESUME_ET_DATE.isoformat()} ET)"
        print(msg)
    else:
        print(
            f"Skipping scheduled run: cron={cron!r} now={now.isoformat()} "
            "(wrong seasonal line, too late / at or after first tip, backup unnecessary, or unknown cron)"
        )

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if ok else 'false'}\n")
            fh.write(f"skip_props={'true' if skip_props else 'false'}\n")


if __name__ == "__main__":
    main()
