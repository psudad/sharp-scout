#!/usr/bin/env python3
"""Run the full pipeline for NFL games kicking off today (US Eastern)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tenacity import RetryError

from sharp_scout.config import DATA_DIR, get_settings  # noqa: E402
from sharp_scout.data.manual_odds import load_manual_slate  # noqa: E402
from sharp_scout.data.odds_api import (  # noqa: E402
    OddsAPIError,
    OddsClient,
    SPORT,
    SPORT_PRESEASON,
    mock_odds_events,
)
from sharp_scout.pipeline.run import run_pipeline  # noqa: E402
from sharp_scout.utils.odds import setup_logging  # noqa: E402

ET = ZoneInfo("America/New_York")


def _today_window_et(date: str | None = None) -> tuple[datetime, datetime, str]:
    """Return UTC start/end for an Eastern calendar day and YYYYMMDD splits key."""
    if date:
        day = datetime.strptime(date, "%Y%m%d").replace(tzinfo=ET)
    else:
        day = datetime.now(ET)
    start_et = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_et = start_et + timedelta(days=1)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc), start_et.strftime("%Y%m%d")


def _filter_today(events: list[dict], start_utc: datetime, end_utc: datetime) -> list[dict]:
    out = []
    for ev in events:
        ct = ev.get("commence_time")
        if ct is None:
            continue
        if isinstance(ct, str):
            ct = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        if start_utc <= ct < end_utc:
            out.append(ev)
    return out


def _resolve_today_events(
    client: OddsClient,
    start_utc: datetime,
    end_utc: datetime,
    splits_date: str,
    slate_path: Path | None = None,
) -> tuple[list[dict], str]:
    """Try regular NFL, preseason Odds API, then optional manual slate file."""
    for sport, label in ((SPORT, "odds_api"), (SPORT_PRESEASON, "odds_api_preseason")):
        try:
            odds = client.fetch_odds(sport=sport)
        except (OddsAPIError, RetryError):
            odds = []
        today = _filter_today(odds, start_utc, end_utc)
        if today:
            return today, label
        try:
            evs = client.fetch_events(sport=sport)
        except (OddsAPIError, RetryError):
            evs = []
        today = _filter_today(evs, start_utc, end_utc)
        if today:
            return today, f"{label}_events_only"

    candidates = []
    if slate_path:
        candidates.append(slate_path)
    candidates.append(DATA_DIR / "slates" / f"{splits_date}.json")
    for path in candidates:
        if not path.exists():
            continue
        events, _ = load_manual_slate(path)
        today = _filter_today(events, start_utc, end_utc)
        if today:
            return today, f"manual_slate:{path.name}"
        if events and path == slate_path:
            return events, f"manual_slate:{path.name}"

    return [], "none"


def main() -> None:
    p = argparse.ArgumentParser(description="Sharp Scout — today's NFL slate (full pipeline)")
    p.add_argument("--date", help="Eastern slate date YYYYMMDD (default: today ET)")
    p.add_argument("--demo", action="store_true", help="Use mock KC@BUF (offline)")
    p.add_argument("--skip-pbp", action="store_true", help="Skip nflverse download")
    p.add_argument("--no-ledger", action="store_true")
    p.add_argument("--fresh-ledger", action="store_true", help="Clear ledger before append")
    p.add_argument("--build-site", action="store_true")
    p.add_argument(
        "--slate",
        type=Path,
        default=None,
        help="Manual slate JSON (default: data/slates/{YYYYMMDD}.json if needed)",
    )
    args = p.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)
    start_utc, end_utc, splits_date = _today_window_et(args.date)

    if args.demo or not settings.odds_api_key:
        events = _filter_today(mock_odds_events(), start_utc, end_utc)
        if not events:
            # Demo kickoff is "now" — force into today window for offline smoke test
            ev = mock_odds_events()[0]
            ev = dict(ev)
            ev["commence_time"] = datetime.now(timezone.utc) + timedelta(hours=4)
            events = [ev]
        demo = True
        skip_pbp = True
        event_source = "demo"
    else:
        client = OddsClient()
        events, event_source = _resolve_today_events(
            client, start_utc, end_utc, splits_date, args.slate
        )
        demo = False
        skip_pbp = args.skip_pbp

    if args.fresh_ledger and not args.no_ledger:
        from sharp_scout.ledger.tracker import empty_ledger, save_ledger

        save_ledger(empty_ledger())

    if not events:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "no_games_today",
                    "splits_date": splits_date,
                    "window_utc": [start_utc.isoformat(), end_utc.isoformat()],
                    "hint": (
                        "No games on regular or preseason Odds API feeds for this Eastern day. "
                        "Add data/slates/{date}.json or pass --slate."
                    ),
                },
                indent=2,
            )
        )
        sys.exit(1)

    result = run_pipeline(
        demo=demo,
        skip_pbp=skip_pbp or demo,
        update_ledger=not args.no_ledger,
        build_pages=args.build_site,
        events=events,
        splits_date=splits_date,
        fetch_splits=not demo,
    )

    summary = {
        "ok": True,
        "event_source": event_source,
        "n_games": result["n_games"],
        "n_candidates": result["n_candidates"],
        "n_validated": result["n_validated"],
        "n_splits_games": result.get("n_splits_games"),
        "games": [
            {
                "matchup": f"{g['away_team']}@{g['home_team']}",
                "kickoff": g.get("commence_time"),
                "model_spread": g.get("model_spread"),
                "model_total": g.get("model_total"),
                "edges": g.get("edge_count"),
                "validated": g.get("validated"),
            }
            for g in result.get("games") or []
        ],
        "plays": [
            {
                "matchup": f"{p.get('away_team')}@{p.get('home_team')}",
                "market": p.get("market"),
                "side": p.get("side"),
                "line": p.get("line"),
                "edge": p.get("edge"),
                "tier": p.get("tier"),
            }
            for p in (result.get("plays") or [])[:10]
        ],
        "site": result.get("site"),
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
