#!/usr/bin/env python3
"""CI gate: skip scheduled props workflows when disabled in config."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import get_settings  # noqa: E402


def main() -> None:
    workflow = (sys.argv[1] if len(sys.argv) > 1 else "nfl").strip().lower()
    settings = get_settings()
    if workflow == "nba":
        enabled = settings.nba_props_scan_enabled
        label = "NBA props scan"
    else:
        enabled = settings.nfl_props_scan_enabled
        label = "NFL props scan"

    proceed = enabled or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if proceed:
        print(f"{label} enabled (or manual workflow_dispatch)")
    else:
        print(f"Skipping: {label} disabled via config (set *_PROPS_SCAN_ENABLED=true to re-enable)")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"proceed={'true' if proceed else 'false'}\n")


if __name__ == "__main__":
    main()
