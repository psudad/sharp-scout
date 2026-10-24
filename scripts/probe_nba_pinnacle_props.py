#!/usr/bin/env python3
"""One-shot probe: does Pinnacle appear on NBA player props in The Odds API?

Usage (costs 1 + N event credits — default N=1):

    python scripts/probe_nba_pinnacle_props.py
    python scripts/probe_nba_pinnacle_props.py --event-id <id> --markets player_points

Exits 0 when the probe completes; prints JSON summary to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys

from sharp_scout.config import get_settings
from sharp_scout.data.odds_api import OddsClient
from sharp_scout.sports import NBA
from sharp_scout.utils.odds import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", default="", help="Optional event id (else first upcoming)")
    parser.add_argument(
        "--markets",
        default="player_points",
        help="Comma-separated prop markets (default: player_points only to save credits)",
    )
    args = parser.parse_args()
    setup_logging("INFO")
    settings = get_settings()
    if not settings.odds_api_key:
        print(json.dumps({"ok": False, "error": "ODDS_API_KEY not set"}))
        return 1

    client = OddsClient(sport=NBA)
    eid = args.event_id
    if not eid:
        events = client.fetch_events()
        if not events:
            print(json.dumps({"ok": False, "error": "no_upcoming_nba_events"}))
            return 1
        eid = str(events[0]["event_id"])

    markets = args.markets
    detail = client.fetch_event_props(eid, markets=markets, regions="us,us2,eu", sport=NBA.odds_sport_key)
    books = detail.get("bookmakers") or {}
    keys = sorted(books.keys())
    pin = books.get("pinnacle")
    summary = {
        "ok": True,
        "event_id": eid,
        "home_team": detail.get("home_team"),
        "away_team": detail.get("away_team"),
        "markets_requested": markets,
        "book_count": len(keys),
        "books": keys,
        "pinnacle_present": pin is not None,
        "pinnacle_markets": sorted((pin.get("markets") or {}).keys()) if pin else [],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
