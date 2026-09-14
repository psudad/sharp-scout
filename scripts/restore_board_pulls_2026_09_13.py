#!/usr/bin/env python3
"""Restore Sunday NFL locked plays that QA voided on 2026-09-13 (not_revalidated)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.copy.explain import collapse_best_signals  # noqa: E402
from sharp_scout.ledger.tracker import (  # noqa: E402
    compute_record,
    load_ledger,
    load_scores_from_schedules,
    save_ledger,
    settle_from_scores,
)
from sharp_scout.site.build import build_site  # noqa: E402

# Four tier:play rows voided after kickoff Sunday when the pipeline re-ran QA.
RESTORE_IDS = frozenset(
    {
        "25580351",  # TB @ CIN spread away +4
        "d5bbfd39",  # BAL @ IND spread home +2.5
        "c7b1e314",  # GB @ MIN ML home
        "7a376739",  # MIA @ LV spread away +3
    }
)

RESTORE_NOTE = {
    "code": "record_restore",
    "severity": "info",
    "message": (
        "Restored to locked weekly record (2026-09-14) — was on the posted board "
        "then voided by QA not_revalidated on 2026-09-13."
    ),
}


def main() -> None:
    path = DATA_DIR / "ledger.json"
    ledger = load_ledger(path)
    restored = 0
    now = datetime.now(timezone.utc).isoformat()
    for play in ledger.get("plays") or []:
        if play.get("id") not in RESTORE_IDS:
            continue
        if play.get("status") != "void":
            print(f"skip {play['id']}: status={play.get('status')}")
            continue
        play["status"] = "pending"
        play["home_score"] = None
        play["away_score"] = None
        play["pnl_units"] = None
        play["settled_at"] = None
        notes = list(play.get("qa_notes") or [])
        notes.append({**RESTORE_NOTE, "at": now})
        play["qa_notes"] = notes
        restored += 1
        print(
            "restored",
            play["away_team"],
            "@",
            play["home_team"],
            play["market"],
            play["side"],
            play.get("line"),
        )

    if not restored:
        print("No plays restored (already pending or missing).")
        return

    save_ledger(ledger, path)
    scores = load_scores_from_schedules(None)
    ledger = settle_from_scores(scores, path=path)
    rec = compute_record(ledger)

    week_locked = collapse_best_signals(
        [
            p
            for p in ledger["plays"]
            if (p.get("status") or "pending") in ("pending", "win", "loss", "push")
            and p.get("tier") == "play"
            and (p.get("kickoff") or "").startswith("2026-09-1")
        ]
    )
    wins = sum(1 for p in week_locked if p.get("status") == "win")
    losses = sum(1 for p in week_locked if p.get("status") == "loss")
    print(f"Restored {restored} play(s). Season record: {rec.get('record')}  pnl={rec.get('pnl_units')}")
    print(f"NFL week (Sep 10–14 kickoffs, deduped locked tier:play): {wins}-{losses}")

    build_site()
    print("Rebuilt docs/.")


if __name__ == "__main__":
    main()
