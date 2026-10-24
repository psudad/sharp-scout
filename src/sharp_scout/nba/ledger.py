"""Shadow ledger for NBA paper trades."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.ledger.tracker import _play_key
from sharp_scout.nba.clv import finalize_nba_clv
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.staking import price_vs_fair_implied


def empty_nba_ledger() -> dict[str, Any]:
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sport": "nba",
        "mode": "shadow",
        "starting_units": 100.0,
        "unit_dollars": 10.0,
        "plays": [],
        "calibration_bins": [],
    }


def load_nba_ledger(path: Path | None = None) -> dict[str, Any]:
    p = path or nba_paths.NBA_LEDGER_PATH
    if not p.exists():
        return empty_nba_ledger()
    data = json.loads(p.read_text())
    data.setdefault("plays", [])
    return data


def save_nba_ledger(ledger: dict[str, Any], path: Path | None = None) -> Path:
    p = path or nba_paths.NBA_LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(ledger, indent=2, default=str) + "\n")
    return p


def append_nba_signals(signals: list[dict[str, Any]], *, path: Path | None = None) -> dict[str, Any]:
    ledger = load_nba_ledger(path)
    existing = {_play_key(p) for p in ledger["plays"]}
    added = 0
    for s in signals:
        row = {
            "id": str(uuid.uuid4())[:8],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "event_id": s.get("event_id"),
            "sport": "nba",
            "kickoff": s.get("kickoff"),
            "away_team": s.get("away_team"),
            "home_team": s.get("home_team"),
            "play_type": s.get("play_type") or "side",
            "player_name": s.get("player_name"),
            "market": s.get("market"),
            "side": s.get("side"),
            "line": s.get("line"),
            "book": s.get("book"),
            "price": s.get("price"),
            "units": s.get("units"),
            "tier": s.get("tier") or "paper",
            "edge": s.get("edge"),
            "p_true": s.get("p_true"),
            "p_mkt": s.get("p_mkt"),
            "p_fair": s.get("p_fair") or s.get("p_mkt"),
            "fair_source": s.get("fair_source"),
            "sharp_book": s.get("sharp_book"),
            "model_mean": s.get("model_mean"),
            "filter_passed": True,
            "pipeline": "nba_shadow",
            "status": "paper",
            "price_vs_fair": price_vs_fair_implied(float(s["price"]), s.get("p_fair") or s.get("p_mkt"))
            if s.get("price") is not None
            else None,
            "close_line": None,
            "close_price": None,
            "close_book": None,
            "clv_points": None,
            "clv_prob": None,
            "clv_at": None,
            "pnl_units": None,
            "settled_at": None,
            "prop_result": None,
        }
        key = _play_key(row)
        if key in existing:
            continue
        ledger["plays"].append(row)
        existing.add(key)
        added += 1
    save_nba_ledger(ledger, path)
    return {"added": added, "ledger": ledger}


def units_staked_today(ledger: dict[str, Any], *, day: str | None = None) -> float:
    day = day or datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    for p in ledger.get("plays") or []:
        created = str(p.get("created_at") or "")[:10]
        if created == day and (p.get("status") or "") in ("paper", "pending"):
            total += float(p.get("units") or 0)
    return total
