"""Paper-only log: follow Pinnacle early NFL totals momentum (not on card or ledger)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR, get_settings
from sharp_scout.data.line_store import closing_sample, load_history, opening_sample, samples_for
from sharp_scout.data.odds_api import is_demo_nfl_event
from sharp_scout.ledger.clv import clv_points
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

PAPER_PATH = DATA_DIR / "paper" / "nfl_totals_momentum_follow.json"

RULE_TEXT = (
    "First scan where Pinnacle full-game total moved ≥0.5 pts from earliest recorded "
    "Pinnacle open in line_history; side follows the move (up → Over, down → Under). "
    "One row per event_id. Graded vs Pinnacle close and final total only."
)


def load_paper_store(path: Path | None = None) -> dict[str, Any]:
    p = path or PAPER_PATH
    if not p.exists():
        return {"version": 1, "rule": RULE_TEXT, "entries": []}
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "rule": RULE_TEXT, "entries": []}
    data.setdefault("entries", [])
    data.setdefault("rule", RULE_TEXT)
    return data


def save_paper_store(store: dict[str, Any], path: Path | None = None) -> Path:
    p = path or PAPER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")
    return p


def _latest_pinnacle_over(event_id: str, history: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    samples = [s for s in samples_for(event_id, "totals", "over", history=history) if s.get("book") == "pinnacle"]
    if not samples:
        return None
    return max(samples, key=lambda s: str(s.get("ts") or ""))


def record_paper_momentum_scans(
    events: list[dict[str, Any]],
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
    path: Path | None = None,
) -> int:
    settings = get_settings()
    min_move = float(settings.paper_nfl_totals_momentum_min_move)
    history = history if history is not None else load_history()
    store = load_paper_store(path)
    have = {str(e.get("event_id")) for e in store.get("entries") or []}
    added = 0

    for ev in events:
        if ev.get("sport") not in (None, "nfl") or is_demo_nfl_event(ev):
            continue
        eid = str(ev.get("event_id") or "")
        if not eid or eid in have:
            continue
        open_s = opening_sample(eid, "totals", "over", history=history)
        latest = _latest_pinnacle_over(eid, history)
        if not open_s or not latest:
            continue
        open_line = float(open_s["line"])
        scan_line = float(latest["line"])
        move = scan_line - open_line
        if abs(move) < min_move:
            continue
        side = "over" if move > 0 else "under"
        store["entries"].append(
            {
                "event_id": eid,
                "home_team": ev.get("home_team"),
                "away_team": ev.get("away_team"),
                "kickoff": (
                    ev.get("commence_time").isoformat()
                    if hasattr(ev.get("commence_time"), "isoformat")
                    else ev.get("commence_time")
                ),
                "scan_ts": latest.get("ts"),
                "open_line": open_line,
                "scan_line": scan_line,
                "move_pts": round(move, 2),
                "side": side,
                "scan_price": int(float(latest["price"])),
                "status": "open",
                "logged_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        have.add(eid)
        added += 1

    if added:
        save_paper_store(store, path)
        logger.info("paper momentum: logged %d NFL totals entries", added)
    return added


def _grade_side(side: str, line: float, final_total: float) -> str:
    if final_total > line:
        winner = "over"
    elif final_total < line:
        winner = "under"
    else:
        return "P"
    return "W" if side == winner else "L"


def grade_paper_momentum_entries(
    scores: list[dict[str, Any]],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    history = load_history()
    store = load_paper_store(path)
    by_match: dict[tuple[str, str], float] = {}
    for s in scores:
        away = normalize_team(str(s.get("away_team") or ""), "nfl") or ""
        home = normalize_team(str(s.get("home_team") or ""), "nfl") or ""
        try:
            by_match[(away, home)] = float(s.get("away_score", 0)) + float(s.get("home_score", 0))
        except (TypeError, ValueError):
            continue

    graded = 0
    for entry in store.get("entries") or []:
        if entry.get("status") == "graded":
            continue
        away = normalize_team(str(entry.get("away_team") or ""), "nfl") or ""
        home = normalize_team(str(entry.get("home_team") or ""), "nfl") or ""
        final_total = by_match.get((away, home))
        if final_total is None:
            continue
        eid = entry.get("event_id")
        close_o = closing_sample(eid, "totals", "over", kickoff=entry.get("kickoff"), history=history)
        if close_o:
            entry["close_line"] = float(close_o["line"])
        side = str(entry.get("side") or "")
        scan_line = float(entry.get("scan_line") or 0)
        entry["final_total"] = final_total
        entry["clv_points"] = clv_points("totals", side, scan_line, entry.get("close_line"))
        entry["result_final"] = _grade_side(side, scan_line, final_total)
        entry["status"] = "graded"
        entry["graded_at"] = datetime.now(timezone.utc).isoformat()
        graded += 1

    if graded:
        save_paper_store(store, path)
    return {"graded": graded, "open": sum(1 for e in store["entries"] if e.get("status") != "graded")}
