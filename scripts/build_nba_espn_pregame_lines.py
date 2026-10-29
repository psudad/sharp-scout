#!/usr/bin/env python3
"""Build backtest-only ESPN line file for NBA games missing repo pre-tip lines."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from nba_espn_summary_lines import fetch_espn_lines_for_event  # noqa: E402
from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.data.espn_nba import fetch_espn_nba_finals_by_event  # noqa: E402
from sharp_scout.nba.score_model.paper import _merged_lines_from_scans, load_paper_store  # noqa: E402
from sharp_scout.nba.score_model.state import _season_start_date  # noqa: E402
from sharp_scout.nba.slate_et import kickoff_date_et  # noqa: E402
from sharp_scout.utils.kickoff import parse_kickoff_utc  # noqa: E402
from sharp_scout.utils.slate import ET  # noqa: E402

OUT_PATH = DATA_DIR / "paper" / "nba_espn_pregame_lines.json"


def _repo_has_lines(store: dict, *, through: date) -> set[tuple[str, str, str]]:
    seen: set[tuple[str, str, str]] = set()
    for g in store.get("games") or []:
        if not g.get("graded"):
            continue
        day = kickoff_date_et(g.get("kickoff"))
        if day is None or day > through:
            continue
        scans = [s for s in g.get("scans") or [] if not s.get("after_tip")]
        merged = _merged_lines_from_scans(scans) if scans else {}
        if merged.get("consensus_spread_home") is None and merged.get("consensus_total") is None:
            continue
        seen.add((str(g.get("away")), str(g.get("home")), day.isoformat()))
    return seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", default="2026-10-28")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    through = date.fromisoformat(args.through)
    store = load_paper_store()
    with_repo = _repo_has_lines(store, through=through)

    season_start = _season_start_date(datetime.combine(through, time(12, 0), tzinfo=ET))
    since = datetime.combine(season_start, datetime.min.time(), tzinfo=timezone.utc)
    until = datetime.combine(through, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
    scores = fetch_espn_nba_finals_by_event(since=since, until=until)

    games: list[dict] = []
    failed: list[dict] = []
    for s in scores:
        kick = parse_kickoff_utc(s["kickoff"])
        day = kickoff_date_et(kick)
        if day is None or day > through:
            continue
        away, home = str(s["away_team"]), str(s["home_team"])
        slot = (away, home, day.isoformat())
        if slot in with_repo:
            continue
        eid = str(s["event_id"])
        parsed = fetch_espn_lines_for_event(eid)
        if not parsed:
            failed.append({"away": away, "home": home, "date_et": day.isoformat(), "espn_event_id": eid})
            continue
        games.append(
            {
                "source": "espn_summary_pickcenter",
                "espn_event_id": eid,
                "date_et": day.isoformat(),
                "kickoff": kick.isoformat() if kick else s.get("kickoff"),
                "away": away,
                "home": home,
                "espn_away_score": int(s["away_score"]),
                "espn_home_score": int(s["home_score"]),
                "lines": {
                    "consensus_spread_home": parsed.get("consensus_spread_home"),
                    "consensus_total": parsed.get("consensus_total"),
                },
                "provider": parsed.get("provider"),
                "line_timing": parsed.get("line_timing"),
                "pickcenter_details": parsed.get("pickcenter_details"),
                "caveat": parsed.get("caveat"),
            }
        )

    doc = {
        "version": 1,
        "notes": (
            "Backtest-only. ESPN summary pickcenter lines for games without Odds API "
            "pre-tip scans in nba_score_model.json. Never merge into live ledgers."
        ),
        "caveat_global": (
            "These lines are usually closing (sometimes open) sportsbook numbers from ESPN, "
            "not T-1h pre-tip consensus snapshots. Backtest grades still use repo close "
            "when available; for ESPN-only games, the same ESPN line is used for pick and grade."
        ),
        "through_date_et": through.isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "games": games,
        "missing_pickcenter": failed,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2, default=str) + "\n")
    print(f"Wrote {len(games)} games to {args.out} ({len(failed)} without pickcenter)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
