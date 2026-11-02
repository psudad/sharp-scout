"""Shadow ledger for NBA Pace of Play spreads (official card is totals-only)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.nba.score_model.official_pace import (
    _grade_published_spread,
    _play_dedupe_key,
    _play_slot_key,
    _slot_already_logged,
    _units_at_110,
)

logger = logging.getLogger(__name__)

SHADOW_PATH = DATA_DIR / "shadow" / "nba_pace_spreads_shadow.json"


def load_spread_shadow(path: Path | None = None) -> dict[str, Any]:
    p = path or SHADOW_PATH
    if not p.exists():
        return {"version": 1, "notes": "Pace spread picks (shadow); totals stay on official card.", "plays": []}
    raw = json.loads(p.read_text())
    raw.setdefault("plays", [])
    return raw


def save_spread_shadow(store: dict[str, Any], path: Path | None = None) -> None:
    p = path or SHADOW_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in store.get("plays") or []:
        seen[_play_dedupe_key(row)] = row
    store["plays"] = list(seen.values())
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")


def append_spread_shadow_play(
    *,
    game_row: dict[str, Any],
    pick: dict[str, Any],
    result: str,
    away_score: int,
    home_score: int,
    store: dict[str, Any] | None = None,
    frozen: dict[str, Any] | None = None,
) -> bool:
    store = store or load_spread_shadow()
    day = kickoff_date_et(game_row.get("kickoff"))
    snap = (frozen or {}).get("snapshot") or {}
    lines = snap.get("lines") or {}
    entry: dict[str, Any] = {
        "id": f"pss-{game_row.get('event_id', '')}-spread",
        "source": "published_spread_shadow",
        "date_et": day.isoformat() if day else None,
        "kickoff": game_row.get("kickoff"),
        "away": game_row.get("away"),
        "home": game_row.get("home"),
        "market": "spread",
        "pick": pick.get("pick"),
        "side": pick.get("side"),
        "line": pick.get("line"),
        "price": -110,
        "gap_pts": round(float(pick.get("gap") or 0), 2),
        "result": result,
        "units": _units_at_110(result),
        "espn_away_score": away_score,
        "espn_home_score": home_score,
        "close_pinnacle_spread_home": lines.get("pinnacle_spread_home"),
        "close_pinnacle_total": lines.get("pinnacle_total"),
        "graded_at": datetime.now(timezone.utc).isoformat(),
    }
    slot = _play_slot_key(
        date_et=str(entry.get("date_et") or ""),
        away=str(entry.get("away") or ""),
        home=str(entry.get("home") or ""),
        market="spread",
    )
    if _slot_already_logged(store, slot):
        return False
    store.setdefault("plays", []).append(entry)
    return True


def sync_spread_shadow_from_paper_store(paper_store: dict[str, Any] | None = None) -> int:
    from sharp_scout.nba.score_model.paper import _game_excluded

    paper_store = paper_store or {}
    store = load_spread_shadow()
    added = 0
    for g in paper_store.get("games") or []:
        if _game_excluded(g) or not g.get("graded"):
            continue
        frozen = g.get("frozen") or {}
        pick = frozen.get("pace_spread_shadow_pick") or g.get("pace_spread_shadow_pick")
        if not pick or pick.get("kind") != "spread":
            continue
        gr = g["graded"]
        cs = gr.get("close_spread_home")
        if cs is None:
            continue
        act_margin = int(gr["actual_margin"])
        act_total = int(gr["actual_total"])
        home_score = (act_total + act_margin) // 2
        away_score = (act_total - act_margin) // 2
        side = str(pick.get("side") or "")
        res = _grade_published_spread(act_margin, close_spread_home=float(cs), side=side)
        if res not in ("win", "loss", "push"):
            continue
        game_row = {
            "kickoff": g.get("kickoff"),
            "away": g.get("away"),
            "home": g.get("home"),
            "event_id": g.get("event_id"),
        }
        if append_spread_shadow_play(
            game_row=game_row,
            pick=pick,
            result=res,
            away_score=away_score,
            home_score=home_score,
            store=store,
            frozen=frozen,
        ):
            added += 1
    if added:
        save_spread_shadow(store)
    return added
