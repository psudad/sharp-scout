#!/usr/bin/env python3
"""One-off data fixes from weekly review 2026-11-02 (Jason-approved)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.ledger.tracker import (  # noqa: E402
    PROPS_LEDGER_PATH,
    american_profit,
    dedupe_props_ledger_plays,
    load_ledger,
    save_ledger,
)
from sharp_scout.nfl.totals.paper_momentum import grade_paper_momentum_entries  # noqa: E402
from sharp_scout.nba.score_model.official_pace import (  # noqa: E402
    load_official_pace,
    save_official_pace,
    sync_auto_pace_from_paper_store,
)
from sharp_scout.nba.score_model.paper import grade_score_model_paper, load_paper_store  # noqa: E402
from sharp_scout.nba.score_model.pace_spreads_shadow import sync_spread_shadow_from_paper_store  # noqa: E402
from sharp_scout.nba.settle import settle_nba_ledger  # noqa: E402
from sharp_scout.data.espn_nba import fetch_espn_nba_scores  # noqa: E402
from sharp_scout.ledger.tracker import load_scores_from_schedules  # noqa: E402


def _patch_pnl(path: Path, play_id_prefix: str, pnl: float) -> bool:
    ledger = load_ledger(path)
    for p in ledger["plays"]:
        if str(p.get("id", "")).startswith(play_id_prefix):
            if p.get("pnl_units") == pnl:
                return False
            p["pnl_units"] = pnl
            save_ledger(ledger, path)
            return True
    return False


def main() -> None:
    changes: list[str] = []

    ncaaf_path = ROOT / "data" / "ncaaf_ledger.json"
    win_pnl = round(american_profit(1.5, -110.0), 4)
    if _patch_pnl(ncaaf_path, "3be12193", win_pnl):
        changes.append(f"ncaaf 3be12193 pnl_units -> {win_pnl}")

    nfl_path = ROOT / "data" / "ledger.json"
    if _patch_pnl(nfl_path, "4dc948aa", -1.5):
        changes.append("nfl 4dc948aa pnl_units -> -1.5")

    props = load_ledger(PROPS_LEDGER_PATH)
    removed = dedupe_props_ledger_plays(props)
    if removed:
        save_ledger(props, PROPS_LEDGER_PATH)
        changes.append(f"props deduped {removed} rows")

    scores = load_scores_from_schedules(None)
    mom = grade_paper_momentum_entries(scores)
    if mom.get("graded"):
        changes.append(f"momentum graded {mom['graded']}")

    nba_scores = fetch_espn_nba_scores(lookback_days=14)
    paper = grade_score_model_paper(scores=nba_scores)
    n_off = sync_auto_pace_from_paper_store(paper)
    n_sp = sync_spread_shadow_from_paper_store(paper)
    if n_off:
        changes.append(f"pace official sync +{n_off}")
    if n_sp:
        changes.append(f"pace spread shadow sync +{n_sp}")

    settle_nba_ledger(scores=nba_scores)

    print("Changes:", changes or ["(ledger patches only)"])


if __name__ == "__main__":
    main()
