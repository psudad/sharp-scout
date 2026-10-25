#!/usr/bin/env python3
"""Recompute football CLV from line_history.json and refresh site record JSON.

Lines are only sampled at pipeline / snapshot run times, so closing lines are the
last sharp sample at or before kickoff among those snapshots — not a continuous feed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.data.line_store import LINE_HISTORY_PATH, load_history  # noqa: E402
from sharp_scout.ledger.clv import finalize_closing_lines, summarize_clv_by_market  # noqa: E402
from sharp_scout.ledger.tracker import LEDGER_PATH, load_ledger, save_ledger  # noqa: E402
from sharp_scout.ncaaf.shadow.ledger import (  # noqa: E402
    flag_logged_after_kickoff,
    load_ledger as load_shadow_ledger,
    save_ledger as save_shadow_ledger,
)
from sharp_scout.ncaaf.shadow.paths import LEDGER_PATH as SHADOW_LEDGER_PATH  # noqa: E402
from sharp_scout.ncaaf.shadow.report import build_summary, write_summary_and_report  # noqa: E402
from sharp_scout.site.build import build_site  # noqa: E402
from sharp_scout.sports import NCAAF  # noqa: E402
from sharp_scout.utils.kickoff import logged_at_or_after_kickoff  # noqa: E402


def _recompute_ledger(path: Path, history: dict, *, label: str) -> dict:
    ledger = load_ledger(path)
    n = finalize_closing_lines(ledger, history=history, force=True)
    save_ledger(ledger, path)
    by_market = summarize_clv_by_market(ledger)
    print(f"[{label}] path={path} clv_rows_updated={n}")
    print(json.dumps({"by_market": by_market}, indent=2))
    return {"path": str(path), "updated": n, "by_market": by_market}


def _audit_official_post_kickoff(path: Path) -> list[dict]:
    ledger = load_ledger(path)
    rows = []
    for p in ledger.get("plays") or []:
        if logged_at_or_after_kickoff(p, logged_at_field="created_at"):
            rows.append(
                {
                    "id": p.get("id"),
                    "game": f"{p.get('away_team')}@{p.get('home_team')}",
                    "kickoff": p.get("kickoff"),
                    "created_at": p.get("created_at"),
                    "market": p.get("market"),
                    "side": p.get("side"),
                }
            )
    return rows


def _shadow_before_after() -> dict:
    ledger = load_shadow_ledger(SHADOW_LEDGER_PATH)
    before = build_summary(ledger, exclude_logged_after_kickoff=False)
    flag_logged_after_kickoff(ledger)
    finalize_closing_lines(ledger, force=True)
    save_shadow_ledger(ledger, SHADOW_LEDGER_PATH)
    after = build_summary(ledger)
    write_summary_and_report(ledger=ledger)
    return {"before": before, "after": after}


def main() -> None:
    p = argparse.ArgumentParser(description="Recompute football CLV and shadow stats")
    p.add_argument("--build-site", action="store_true", help="Rebuild docs/ after recompute")
    args = p.parse_args()

    history = load_history(LINE_HISTORY_PATH)
    nfl_path = LEDGER_PATH
    ncaaf_path = DATA_DIR / NCAAF.ledger_name

    report = {
        "history_path": str(LINE_HISTORY_PATH),
        "n_history_keys": len(history),
        "ledgers": [
            _recompute_ledger(nfl_path, history, label="nfl"),
            _recompute_ledger(ncaaf_path, history, label="ncaaf"),
        ],
        "official_logged_after_kickoff": {
            "nfl": _audit_official_post_kickoff(nfl_path),
            "ncaaf": _audit_official_post_kickoff(ncaaf_path),
        },
        "ncaaf_totals_shadow": _shadow_before_after(),
    }
    out = ROOT / "reports" / "football_clv_recompute.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"Wrote {out}")

    if args.build_site:
        build_site()
        print("Rebuilt docs/")


if __name__ == "__main__":
    main()
