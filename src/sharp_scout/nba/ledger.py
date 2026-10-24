"""Shadow ledger for NBA paper trades."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
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


def is_demo_nba_row(row: dict[str, Any]) -> bool:
    if row.get("demo"):
        return True
    return str(row.get("event_id") or "").startswith("demo-")


def parse_kickoff_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def kickoff_still_future(row: dict[str, Any], *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    kick = parse_kickoff_utc(row.get("kickoff"))
    if kick is None:
        return False
    return kick > now


def kickoff_in_horizon(
    value: Any,
    hours: float,
    *,
    now: datetime | None = None,
) -> bool:
    """True when kickoff is strictly after *now* and within *hours* (same window as props)."""
    now = now or datetime.now(timezone.utc)
    kick = parse_kickoff_utc(value)
    if kick is None:
        return False
    horizon = now + timedelta(hours=hours)
    return kick > now and kick <= horizon


def strip_demo_plays_from_ledger(ledger: dict[str, Any]) -> tuple[dict[str, Any], int]:
    before = len(ledger.get("plays") or [])
    plays = [p for p in ledger.get("plays") or [] if not is_demo_nba_row(p)]
    out = dict(ledger)
    out["plays"] = plays
    return out, before - len(plays)


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
        if not is_demo_nba_row(s) and not kickoff_still_future(s):
            continue
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


def ledger_play_to_signal(play: dict[str, Any]) -> dict[str, Any]:
    """Shape an open ledger row for the latest-signals Picks list."""
    return {
        "event_id": play.get("event_id"),
        "sport": "nba",
        "kickoff": play.get("kickoff"),
        "away_team": play.get("away_team"),
        "home_team": play.get("home_team"),
        "play_type": play.get("play_type") or "side",
        "player_name": play.get("player_name"),
        "market": play.get("market"),
        "side": play.get("side"),
        "line": play.get("line"),
        "book": play.get("book"),
        "price": play.get("price"),
        "units": play.get("units"),
        "tier": play.get("tier") or "paper",
        "edge": play.get("edge"),
        "p_true": play.get("p_true"),
        "p_mkt": play.get("p_mkt"),
        "p_fair": play.get("p_fair"),
        "fair_source": play.get("fair_source"),
        "sharp_book": play.get("sharp_book"),
        "model_mean": play.get("model_mean"),
        "filter_passed": True,
        "pipeline": play.get("pipeline") or "nba_shadow",
        "status": play.get("status") or "paper",
        "ledger_id": play.get("id"),
        "from_ledger": True,
    }


def merge_open_ledger_picks(
    signals: list[dict[str, Any]],
    possible_signals: list[dict[str, Any]],
    ledger: dict[str, Any],
    *,
    live_scan: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep open future ledger plays visible as Picks on live re-scans."""
    from sharp_scout.config import get_settings
    from sharp_scout.nba.possible import pick_dedupe_key

    if not live_scan:
        return signals, possible_signals

    horizon_hours = get_settings().nba_prop_horizon_hours
    open_status = {"paper", "pending"}
    keys = {pick_dedupe_key(s) for s in signals if not is_demo_nba_row(s)}
    merged = [s for s in signals if not is_demo_nba_row(s)]
    for play in ledger.get("plays") or []:
        if str(play.get("status") or "").lower() not in open_status:
            continue
        if is_demo_nba_row(play):
            continue
        if not kickoff_still_future(play):
            continue
        if not kickoff_in_horizon(play.get("kickoff"), horizon_hours):
            continue
        sig = ledger_play_to_signal(play)
        key = pick_dedupe_key(sig)
        if key in keys:
            continue
        merged.append(sig)
        keys.add(key)
    possible = [
        p
        for p in possible_signals
        if not is_demo_nba_row(p) and pick_dedupe_key(p) not in keys
    ]
    return merged, possible


def filter_demo_from_signal_lists(
    signals: list[dict[str, Any]],
    possible_signals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        [s for s in signals if not is_demo_nba_row(s)],
        [p for p in possible_signals if not is_demo_nba_row(p)],
    )


def units_staked_today(ledger: dict[str, Any], *, day: str | None = None) -> float:
    day = day or datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    for p in ledger.get("plays") or []:
        if is_demo_nba_row(p):
            continue
        created = str(p.get("created_at") or "")[:10]
        if created == day and (p.get("status") or "") in ("paper", "pending"):
            total += float(p.get("units") or 0)
    return total
