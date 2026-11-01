"""Grade NCAAM ledger from ESPN finals."""

from __future__ import annotations

import logging
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR
from sharp_scout.ledger.clv import finalize_closing_lines
from sharp_scout.ledger.tracker import american_profit, load_ledger, save_ledger
from sharp_scout.ncaam.espn import fetch_final_scores
from sharp_scout.utils.slate import parse_commence

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
LEDGER_PATH = DATA_DIR / "ncaam_ledger.json"


def _grade_spread(side: str, line: float, home_score: int, away_score: int) -> str:
    margin = home_score - away_score
    if side == "home":
        diff = margin + float(line)
    else:
        diff = away_score - home_score + float(line)
    if abs(diff) < 1e-9:
        return "push"
    return "win" if diff > 0 else "loss"


def _grade_h2h(side: str, home_score: int, away_score: int) -> str:
    if home_score == away_score:
        return "push"
    home_won = home_score > away_score
    return "win" if (side == "home") == home_won else "loss"


def settle_ncaam_ledger(
    *,
    path: Path | None = None,
    scores: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    path = path or LEDGER_PATH
    ledger = load_ledger(path)
    if scores is None:
        today = date.today()
        scores = fetch_final_scores(start=today - timedelta(days=2), end=today)
    by_id = {str(s.get("espn_id") or s.get("event_id")): s for s in scores}
    changed = False
    for play in ledger.get("plays") or []:
        if play.get("status") in ("win", "loss", "push", "void", "no_play", "missed"):
            if play.get("settled_at") and play.get("status") in ("win", "loss", "push", "void"):
                continue
        if play.get("status") in ("no_play", "missed"):
            continue
        if not play.get("side"):
            continue
        eid = str(play.get("espn_id") or play.get("event_id") or "")
        score = by_id.get(eid)
        if not score:
            continue
        hs, aw = int(score["home_score"]), int(score["away_score"])
        mkt = play.get("market") or "spreads"
        if mkt == "h2h":
            result = _grade_h2h(str(play.get("side")), hs, aw)
        else:
            if play.get("line") is None:
                continue
            result = _grade_spread(str(play.get("side")), float(play["line"]), hs, aw)
        play["status"] = result
        play["home_score"] = hs
        play["away_score"] = aw
        units = float(play.get("units") or 1.0)
        if result == "win":
            play["pnl_units"] = round(american_profit(units, float(play.get("price") or -110)), 3)
        elif result == "push":
            play["pnl_units"] = 0.0
        else:
            play["pnl_units"] = -units
        play["settled_at"] = __import__("datetime").datetime.now(timezone.utc).isoformat()
        changed = True
    if changed:
        save_ledger(ledger, path)
    try:
        finalize_closing_lines(ledger, path=path)
        save_ledger(ledger, path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CLV finalize failed: %s", exc)
    return ledger
