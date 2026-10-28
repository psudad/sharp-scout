#!/usr/bin/env python3
"""Replay Pace of Play picks for stored ET dates (offline; uses data/paper/nba_score_model.json)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR
from sharp_scout.nba.score_model.pace_qualify import pace_display_pick_from_snapshot, pace_min_gap_pts
from sharp_scout.nba.score_model.paper import _merged_lines_from_scans
from sharp_scout.nba.score_model.state import ensure_score_engine
from sharp_scout.nba.slate_et import kickoff_date_et


def _games_on(store: dict, day: date) -> list[dict]:
    out = []
    for g in store.get("games") or []:
        if kickoff_date_et(g.get("kickoff")) == day:
            out.append(g)
    return out


def replay_day(store: dict, day: date, *, engine) -> list[dict]:
    rows = []
    min_default = pace_min_gap_pts(engine=engine, home="NYK", away="BOS")
    for g in _games_on(store, day):
        home, away = str(g.get("home")), str(g.get("away"))
        scans = g.get("scans") or []
        if not scans:
            continue
        snap = dict(scans[-1])
        merged = _merged_lines_from_scans(scans)
        if merged:
            snap["lines"] = merged
        frozen = g.get("frozen") or {}
        tip = dict(frozen.get("snapshot") or snap)
        if merged:
            tip["lines"] = merged
        pick_old = (frozen.get("pace_display_pick") or {}).get("pick")
        pick_new = pace_display_pick_from_snapshot(tip, home=home, away=away, engine=engine)
        rows.append(
            {
                "date_et": day.isoformat(),
                "matchup": f"{away} @ {home}",
                "published_pick": pick_old,
                "replay_pick": (pick_new or {}).get("pick"),
                "replay_gap": (pick_new or {}).get("gap"),
                "large_gap_warning": (pick_new or {}).get("large_gap_warning"),
                "min_gap": pace_min_gap_pts(engine=engine, home=home, away=away),
                "graded": bool(g.get("graded")),
            }
        )
    rows.sort(key=lambda r: r["matchup"])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dates",
        default="2026-10-25,2026-10-26,2026-10-27",
        help="Comma-separated ET dates",
    )
    parser.add_argument(
        "--paper",
        type=Path,
        default=DATA_DIR / "paper" / "nba_score_model.json",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    store = json.loads(args.paper.read_text())
    engine = ensure_score_engine()
    days = [date.fromisoformat(x.strip()) for x in args.dates.split(",") if x.strip()]
    report: dict[str, list[dict]] = {}
    for d in days:
        report[d.isoformat()] = replay_day(store, d, engine=engine)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print("NBA Pace replay (stored scans + new qualification rules)\n")
    for d in days:
        print(f"=== {d.isoformat()} (ET) ===")
        for row in report[d.isoformat()]:
            pub = row["published_pick"] or "—"
            new = row["replay_pick"] or "—"
            ch = " (changed)" if pub != new else ""
            print(
                f"  {row['matchup']}: was {pub} → now {new} "
                f"[gap {row['replay_gap']}, min {row['min_gap']}, warn={row['large_gap_warning']}]{ch}"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
