"""Grade NCAAF totals shadow plays and attach CLV from line_history."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sharp_scout.ledger.clv import finalize_closing_lines
from sharp_scout.ledger.tracker import load_scores_from_cfb_schedules, settle_play
from sharp_scout.ncaaf.shadow import paths
from sharp_scout.ncaaf.shadow.ledger import flag_logged_after_kickoff, load_ledger, save_ledger
from sharp_scout.settlement.score_match import build_score_index, match_play_to_score
from sharp_scout.utils.slate import parse_commence

logger = logging.getLogger(__name__)


def _merge_score_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rows in groups:
        for row in rows:
            key = (
                str(row.get("event_id") or "")
                or f"{row.get('away_team')}@{row.get('home_team')}:{row.get('season')}:{row.get('week')}"
            )
            if not key:
                key = f"{row.get('away_team')}@{row.get('home_team')}"
            out[key] = row
    return list(out.values())


def settle_shadow_ledger(
    *,
    ledger_path: Path | None = None,
    scores: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ledger = load_ledger(ledger_path)
    shadow_path = ledger_path or paths.LEDGER_PATH
    shadow_scores = load_scores_from_cfb_schedules(None, ledger_path=shadow_path)
    if scores is None:
        scores = shadow_scores
    else:
        scores = _merge_score_rows(scores, shadow_scores)

    index = build_score_index(scores, sport="ncaaf")

    graded = 0
    ambiguous = 0
    unmatched = 0
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    for play in ledger.get("plays") or []:
        if (play.get("status") or "pending") != "pending":
            continue
        kick = parse_commence(play.get("kickoff"))
        if kick is not None and kick > now:
            continue
        result = match_play_to_score(
            play,
            index,
            sport="ncaaf",
            allow_home_away_swap=True,  # totals only — never enable for spreads/ML
        )
        if result.reason == "ambiguous":
            ambiguous += 1
            continue
        g = result.score
        if not g or g.get("home_score") is None or g.get("away_score") is None:
            unmatched += 1
            continue
        row = dict(play)
        row["units"] = float(ledger.get("unit_stake") or 1.0)
        settled = settle_play(row, int(g["home_score"]), int(g["away_score"]))
        play.update(
            {
                "status": settled.get("status"),
                "pnl_units": settled.get("pnl_units"),
                "home_score": settled.get("home_score"),
                "away_score": settled.get("away_score"),
                "settled_at": settled.get("settled_at"),
                "units": row["units"],
            }
        )
        graded += 1

    flag_logged_after_kickoff(ledger)
    clv_updated = finalize_closing_lines(ledger, force=False)
    save_ledger(ledger, ledger_path)
    logger.info(
        "NCAAF totals shadow: graded=%d ambiguous=%d unmatched=%d clv_updated=%d",
        graded,
        ambiguous,
        unmatched,
        clv_updated,
    )
    return {
        "graded": graded,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "clv_updated": clv_updated,
        "ledger": ledger,
    }
