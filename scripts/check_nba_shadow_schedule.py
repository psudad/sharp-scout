#!/usr/bin/env python3
"""CI gate: scheduled NBA shadow runs only at weekday 4:30 PM / weekend 11:00 AM ET."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba.schedule_guard import scheduled_slot_matches  # noqa: E402


def main() -> None:
    now = datetime.now(timezone.utc)
    ok = scheduled_slot_matches(now)
    if ok:
        print(f"Within NBA shadow scheduled ET window at {now.isoformat()}")
    else:
        print(f"Outside NBA shadow scheduled ET window at {now.isoformat()} — skip run")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if ok else 'false'}\n")


if __name__ == "__main__":
    main()
