#!/usr/bin/env python3
"""One command to 'settle the ledger': grade finished NFL + NCAAF games from public
final scores, rebuild the site, and (optionally) commit & push so the live board
updates. Designed to be run by a Cursor cloud agent — it needs no API keys, since
settlement reads only public score feeds (ESPN / nflverse / cfbfastR).

Usage:
  python scripts/settle_now.py            # settle both sports + rebuild docs/ (no push)
  python scripts/settle_now.py --push     # also commit & push (updates the live site)
  python scripts/settle_now.py --sport ncaaf --push
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.ledger.tracker import (  # noqa: E402
    compute_record,
    load_ledger,
    load_scores_from_cfb_schedules,
    load_scores_from_schedules,
    settle_from_scores,
)
from sharp_scout.site.build import build_site  # noqa: E402
from sharp_scout.sports import get_sport  # noqa: E402


def _pending(ledger: dict) -> int:
    return sum(1 for p in ledger.get("plays", []) if (p.get("status") or "pending") == "pending")


def _settle_one(sport_key: str) -> dict:
    sport = get_sport(sport_key)
    ledger_path = DATA_DIR / sport.ledger_name
    before = _pending(load_ledger(path=ledger_path))
    if sport.key == "ncaaf":
        scores = load_scores_from_cfb_schedules(None)
    else:
        scores = load_scores_from_schedules(None)
    ledger = settle_from_scores(scores, path=ledger_path)
    after = _pending(ledger)
    rec = compute_record(ledger)
    graded = before - after
    play_rec = (rec.get("plays") or rec).get("record") if isinstance(rec, dict) else None
    print(
        f"[{sport.key}] scores={len(scores)}  newly graded={max(graded, 0)}  "
        f"still pending={after}  record={play_rec or rec.get('record', '?')}"
    )
    return {"sport": sport.key, "graded": max(graded, 0), "pending": after}


def _git(*args: str) -> int:
    return subprocess.call(["git", *args], cwd=str(ROOT))


def main() -> None:
    p = argparse.ArgumentParser(description="Settle the ledger (NFL + NCAAF) and rebuild the site")
    p.add_argument("--sport", choices=["nfl", "ncaaf", "both"], default="both")
    p.add_argument("--push", action="store_true", help="commit & push so the live site updates")
    args = p.parse_args()

    sports = ["nfl", "ncaaf"] if args.sport == "both" else [args.sport]
    results = [_settle_one(s) for s in sports]

    build_site()
    print("Rebuilt docs/ from settled ledgers.")

    total_graded = sum(r["graded"] for r in results)
    if not args.push:
        print(f"Done — {total_graded} play(s) graded. (Run with --push to update the live site.)")
        return

    _git("config", "user.name", "sharp-scout-bot")
    _git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    _git("add", "data/ledger.json", "data/ncaaf_ledger.json", "docs")
    if _git("diff", "--staged", "--quiet") == 0:
        print("Nothing changed — no commit needed.")
        return
    _git("commit", "-m", f"chore: settle ledger ({total_graded} graded) + rebuild site")
    if _git("push") == 0:
        print(f"Pushed — live site will redeploy. {total_graded} play(s) graded.")
    else:
        print("Commit made but push failed — check the branch/remote.", file=sys.stderr)


if __name__ == "__main__":
    main()
