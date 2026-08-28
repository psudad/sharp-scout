#!/usr/bin/env python3
"""Fetch live odds and append timestamped sharp lines (CLV closing lines + steam)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import get_settings  # noqa: E402
from sharp_scout.data.line_store import LINE_HISTORY_PATH, load_history, record_snapshot  # noqa: E402
from sharp_scout.data.odds_api import OddsClient, mock_ncaaf_odds_events, mock_odds_events  # noqa: E402
from sharp_scout.sports import get_sport  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Record sharp line snapshots for CLV / steam")
    p.add_argument("--sport", choices=["nfl", "ncaaf"], default="nfl")
    p.add_argument("--demo", action="store_true", help="Use mock odds (no API key)")
    args = p.parse_args()

    sport = get_sport(args.sport)
    settings = get_settings()
    before = sum(len(v) for v in load_history().values())

    if args.demo or not settings.odds_api_key:
        events = mock_ncaaf_odds_events() if sport.key == "ncaaf" else mock_odds_events()
    else:
        events = OddsClient(sport=sport.key).fetch_odds()

    record_snapshot(events)
    after = sum(len(v) for v in load_history().values())
    print(
        json.dumps(
            {
                "sport": sport.key,
                "n_events": len(events),
                "samples_added": after - before,
                "history_path": str(LINE_HISTORY_PATH),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
