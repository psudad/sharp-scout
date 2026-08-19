#!/usr/bin/env python3
"""Diagnose Action Network cookie / Pro splits access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.data.action_network import ActionNetworkClient  # noqa: E402
from sharp_scout.utils.odds import setup_logging  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Check Action Network splits access")
    p.add_argument(
        "--cookie",
        default=None,
        help="Override ACTION_NETWORK_COOKIE (paste full Cookie header value)",
    )
    p.add_argument("--date", default=None, help="YYYYMMDD optional slate date")
    p.add_argument(
        "--league",
        default="nfl",
        choices=["nfl", "ncaaf"],
        help="Action Network league slug (nfl or ncaaf)",
    )
    args = p.parse_args()
    setup_logging("INFO")

    client = ActionNetworkClient(cookie=args.cookie, league=args.league)
    # If date passed, still run diagnose on fetch with date
    if args.date:
        games = client.fetch_scoreboard(date=args.date)
        report = client.diagnose()
        report["n_games"] = len(games)
    else:
        report = client.diagnose()

    print(json.dumps(report, indent=2, default=str))
    if not report.get("pro_splits_ready"):
        print(
            "\nHow to grab the cookie:\n"
            "  1. Open https://www.actionnetwork.com and log in (Pro/EDGE).\n"
            "  2. Go to NFL or NCAAF Public Betting.\n"
            "  3. DevTools → Network → pick a scoreboard/api request.\n"
            "  4. Request Headers → copy the full Cookie value.\n"
            "  5. Local: ACTION_NETWORK_COOKIE='...' in .env\n"
            "  6. GitHub: Settings → Secrets → ACTION_NETWORK_COOKIE\n"
            "  Cookies expire — re-copy when diagnose fails.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
