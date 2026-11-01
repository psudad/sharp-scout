#!/usr/bin/env python3
"""Count-only check that Action Network NCAAB money % reaches automated runs.

Prints whether a token is configured (yes/no), the auth mode used, the HTTP status and
game counts. Never prints the token, cookie or any header. Spends no Odds API credits.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.ncaam.splits import fetch_splits  # noqa: E402


def main() -> int:
    has_token = bool(os.environ.get("ACTION_NETWORK_TOKEN"))
    has_cookie = bool(os.environ.get("ACTION_NETWORK_COOKIE"))
    today = datetime.now(ZoneInfo("America/New_York")).date()
    days = [today + timedelta(days=i) for i in range(0, 4)]
    res = fetch_splits(days)
    games = res.get("games") or []
    print(f"token_configured={'yes' if has_token else 'no'} cookie_configured={'yes' if has_cookie else 'no'}")
    print(f"auth_mode={res.get('auth_mode')} http_status={res.get('status')}")
    print(f"days={days[0]}..{days[-1]} games={len(games)} games_with_money_pct={res.get('n_with_money')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
