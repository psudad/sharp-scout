#!/usr/bin/env python3
"""Gate ncaaf.yml scheduled runs: primary slots always run; backups only if last_rebuild is stale."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_ncaaf_staleness import needs_pipeline_backup_refresh  # noqa: E402

# Primary cron lines (always run full pipeline when scheduled).
PRIMARY_CRONS = frozenset(
    {
        "7 15 * * 1-6",  # ~11:07 AM ET Mon–Sat
        "23 18 * * 6",  # ~2:23 PM ET Sat
        "7 22 * * 5,6",  # ~6:07 PM ET Fri/Sat
        "7 12 * * 0",  # ~8:07 AM ET Sun
    }
)

# Backup crons (+25 / +50 min after each primary).
BACKUP_CRONS = frozenset(
    {
        "32 15 * * 1-6",
        "57 15 * * 1-6",
        "48 18 * * 6",
        "13 19 * * 6",
        "32 22 * * 5,6",
        "57 22 * * 5,6",
        "32 12 * * 0",
        "57 12 * * 0",
    }
)


def main() -> None:
    event = os.environ.get("GITHUB_EVENT_NAME", "schedule").strip()
    cron = os.environ.get("GITHUB_SCHEDULE_CRON", "").strip()

    if event != "schedule":
        print("Non-schedule event — run pipeline")
        _set_output(True)
        return

    if cron in PRIMARY_CRONS:
        print(f"Primary slot {cron!r} — always run")
        _set_output(True)
        return

    if cron in BACKUP_CRONS:
        run = needs_pipeline_backup_refresh()
        _set_output(run)
        return

    print(f"Unknown schedule cron {cron!r} — skip")
    _set_output(False)


def _set_output(run: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if run else 'false'}\n")
    if not run:
        sys.exit(0)


if __name__ == "__main__":
    main()
