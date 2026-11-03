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
NCAAM_LINE_HISTORY_PATH = DATA_DIR / "ncaam" / "line_history.json"
# Owner-approved corrections to locked rows (voids, team-label fixes). Re-applied on every pass so
# they survive a runner that was started on older code and pushes its own copy of the ledger.
MANUAL_OVERRIDES_PATH = DATA_DIR / "ncaam" / "manual_overrides.json"


def apply_manual_overrides(
    ledger: dict[str, Any], *, ledger_name: str, path: Path | None = None
) -> bool:
    """Apply manual_overrides.json entries for this ledger file. Returns True if anything changed.

    ``void``: status void, 0u stake, 0u P&L (never counted in W-L or units).
    ``set``: overwrite the listed fields (e.g. the team label on a neutral-site flip).
    """
    import json

    p = path or MANUAL_OVERRIDES_PATH
    try:
        overrides = json.loads(p.read_text()).get("overrides") or []
    except (OSError, ValueError):
        return False
    by_id = {str(o.get("id")): o for o in overrides if o.get("ledger") == ledger_name and o.get("id")}
    if not by_id:
        return False
    changed = False
    for play in ledger.get("plays") or []:
        o = by_id.get(str(play.get("id")))
        if not o:
            continue
        if o.get("action") == "void":
            want = {
                "status": "void",
                "units": 0.0,
                "pnl_units": 0.0,
                "void_reason": o.get("reason"),
            }
        elif o.get("action") == "set":
            want = {**(o.get("fields") or {}), "correction_note": o.get("reason")}
        else:
            continue
        diff = {k: v for k, v in want.items() if play.get(k) != v}
        if diff:
            play.update(diff)
            changed = True
        if o.get("approved_at") and play.get("overridden_at") != o.get("approved_at"):
            play["overridden_at"] = o.get("approved_at")
            changed = True
    return changed


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
    changed = apply_manual_overrides(ledger, ledger_name=path.name)
    if scores is None:
        today = date.today()
        scores = fetch_final_scores(start=today - timedelta(days=2), end=today)
    by_id = {str(s.get("espn_id") or s.get("event_id")): s for s in scores}
    for play in ledger.get("plays") or []:
        if play.get("status") == "void":
            continue
        if play.get("status") in ("no_play", "missed"):
            continue
        if play.get("status") in ("win", "loss", "push") and play.get("settled_at"):
            continue
        if not play.get("side"):
            continue
        eid = str(play.get("espn_id") or play.get("event_id") or "")
        score = by_id.get(eid)
        if not score:
            continue
        hs, aw = int(score["home_score"]), int(score["away_score"])
        # Grade by team name, not ESPN position: on neutral sites ESPN can list the teams the
        # other way round from the ledger row (which uses the Odds API frame).
        ph, pa = play.get("home_team"), play.get("away_team")
        sh, sa = score.get("home_team"), score.get("away_team")
        if ph and pa and (ph, pa) == (sa, sh) and ph != pa:
            hs, aw = aw, hs
        mkt = play.get("market") or "spreads"
        if mkt == "h2h":
            result = _grade_h2h(str(play.get("side")), hs, aw)
        else:
            if play.get("line") is None:
                continue
            result = _grade_spread(str(play.get("side")), float(play["line"]), hs, aw)
        play["status"] = result
        play["home_score"] = hs  # in the ledger row's home/away frame
        play["away_score"] = aw
        raw_units = play.get("units")
        units = 1.0 if raw_units is None else float(raw_units)
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
        n = finalize_closing_lines(ledger, history_path=NCAAM_LINE_HISTORY_PATH)
        if n:
            save_ledger(ledger, path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CLV finalize failed: %s", exc)
    return ledger
