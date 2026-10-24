"""Grade NCAAF totals shadow plays and attach CLV from line_history."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sharp_scout.ledger.clv import finalize_closing_lines
from sharp_scout.ledger.tracker import load_scores_from_cfb_schedules, settle_play
from sharp_scout.ncaaf.shadow import paths
from sharp_scout.ncaaf.shadow.ledger import load_ledger, save_ledger
from sharp_scout.utils.slate import parse_commence

logger = logging.getLogger(__name__)


def _match_score(play: dict[str, Any], scores: list[dict[str, Any]]) -> dict[str, Any] | None:
    away = (play.get("away_team") or "").upper()
    home = (play.get("home_team") or "").upper()
    kick = parse_commence(play.get("kickoff"))
    for g in scores:
        if (g.get("away_team") or "").upper() != away:
            continue
        if (g.get("home_team") or "").upper() != home:
            continue
        gkick = parse_commence(g.get("commence_time") or g.get("kickoff"))
        if kick and gkick and abs((kick - gkick).total_seconds()) > 36 * 3600:
            continue
        return g
    return None


def settle_shadow_ledger(
    *,
    ledger_path: Path | None = None,
    scores: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ledger = load_ledger(ledger_path)
    if scores is None:
        scores = load_scores_from_cfb_schedules(None, ledger_path=None)

    graded = 0
    for play in ledger.get("plays") or []:
        if (play.get("status") or "pending") != "pending":
            continue
        g = _match_score(play, scores)
        if not g or g.get("home_score") is None or g.get("away_score") is None:
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

    clv_updated = finalize_closing_lines(ledger)
    save_ledger(ledger, ledger_path)
    logger.info("NCAAF totals shadow: graded=%d clv_updated=%d", graded, clv_updated)
    return {"graded": graded, "clv_updated": clv_updated, "ledger": ledger}
