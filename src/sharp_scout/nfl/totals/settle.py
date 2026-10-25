"""Grade NFL totals board rows from final scores."""

from __future__ import annotations

import logging
from typing import Any

from sharp_scout.nfl.totals.tracker import load_totals_board, save_totals_board
from sharp_scout.utils.odds import normalize_team
from sharp_scout.utils.slate import parse_commence

logger = logging.getLogger(__name__)


def _kickoff_date_key(kickoff: Any) -> str | None:
    kick = parse_commence(kickoff)
    if kick is None:
        return None
    return kick.astimezone(__import__("datetime").timezone.utc).date().isoformat()


def match_score_row(
    game_row: dict[str, Any],
    scores: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Match by event_id, then season/week/teams, then kickoff date + teams."""
    eid = str(game_row.get("event_id") or "")
    away = normalize_team(str(game_row.get("away_team") or ""), "nfl")
    home = normalize_team(str(game_row.get("home_team") or ""), "nfl")
    season = game_row.get("season")
    week = game_row.get("week")
    kdate = _kickoff_date_key(game_row.get("kickoff") or game_row.get("commence_time"))

    by_eid = {str(s.get("event_id") or ""): s for s in scores if s.get("event_id")}
    if eid and eid in by_eid:
        return by_eid[eid]

    candidates: list[dict[str, Any]] = []
    for s in scores:
        sa = normalize_team(str(s.get("away_team") or ""), "nfl")
        sh = normalize_team(str(s.get("home_team") or ""), "nfl")
        if sa != away or sh != home:
            continue
        if season is not None and week is not None:
            if s.get("season") == season and s.get("week") == week:
                return s
        candidates.append(s)

    if kdate:
        for s in candidates:
            gd = s.get("gameday") or s.get("kickoff") or s.get("commence_time")
            if _kickoff_date_key(gd) == kdate:
                return s

    if len(candidates) == 1:
        return candidates[0]
    return None


def grade_totals_board(
    scores: list[dict[str, Any]],
) -> int:
    board = load_totals_board()
    regraded = 0
    for row in board.get("games") or []:
        if row.get("status") == "void":
            continue
        hit = match_score_row(row, scores)
        if not hit or hit.get("home_score") is None:
            continue
        hs, as_ = int(hit["home_score"]), int(hit["away_score"])
        line = row.get("market_line")
        lean = row.get("sim_lean")
        if line is None or lean not in ("over", "under"):
            continue
        total = hs + as_
        if total > float(line):
            result = "win" if lean == "over" else "loss"
        elif total < float(line):
            result = "win" if lean == "under" else "loss"
        else:
            result = "push"
        old_result = row.get("result")
        old_hs, old_as = row.get("home_score"), row.get("away_score")
        if old_result != result or old_hs != hs or old_as != as_:
            regraded += 1
        row["home_score"] = hs
        row["away_score"] = as_
        row["result"] = result
        row["status"] = "settled"
        row["graded_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
    save_totals_board(board)
    logger.info("NFL totals board: regraded/updated %d rows", regraded)
    return regraded
