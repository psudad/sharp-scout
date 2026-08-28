#!/usr/bin/env python3
"""Remove stale NFL signal artifacts (e.g. preseason manual slates)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import ARTIFACTS_DIR  # noqa: E402
from sharp_scout.site.build import build_site  # noqa: E402


def empty_signals() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": now,
        "demo": False,
        "n_games": 0,
        "n_candidates": 0,
        "n_validated": 0,
        "games": [],
        "signals": [],
        "plays": [],
        "stage_picks": [],
        "stage_summary": {},
        "ratings": [],
        "split_boards": [],
    }


def main() -> None:
    payload = empty_signals()
    out = ARTIFACTS_DIR / "latest_signals.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    site = build_site()
    print(json.dumps({"cleared": str(out), "site": str(site)}, indent=2))


if __name__ == "__main__":
    main()
