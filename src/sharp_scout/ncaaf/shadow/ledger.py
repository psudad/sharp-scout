"""Shadow ledger for NCAAF totals with EV above the public card ceiling."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.ncaaf.shadow import paths


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def play_key(event_id: str | None, side: str | None, *, bucket: str) -> str:
    return f"{event_id or ''}|totals|{side or ''}|{bucket}"


def empty_ledger() -> dict[str, Any]:
    return {
        "updated_at": _now(),
        "sport": "ncaaf",
        "market": "totals",
        "mode": "shadow_high_ev",
        "unit_stake": 1.0,
        "plays": [],
    }


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    p = path or paths.LEDGER_PATH
    if not p.exists():
        return empty_ledger()
    data = json.loads(p.read_text())
    data.setdefault("plays", [])
    return data


def save_ledger(ledger: dict[str, Any], path: Path | None = None) -> Path:
    p = path or paths.LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = _now()
    p.write_text(json.dumps(ledger, indent=2, default=str) + "\n")
    return p


def _snapshot_fields(signal: dict[str, Any], *, at: str, season: int | None, week: int | None) -> dict[str, Any]:
    away = signal.get("away_team") or ""
    home = signal.get("home_team") or ""
    return {
        "line": signal.get("line"),
        "price": signal.get("price"),
        "book": signal.get("book"),
        "edge": signal.get("edge"),
        "p_fair": signal.get("p_fair"),
        "p_mkt": signal.get("p_mkt"),
        "sharp_price": signal.get("sharp_price"),
        "sharp_book": signal.get("sharp_book"),
        "flags": signal.get("flags") or {},
        "filter_passed": bool(signal.get("filter_passed")),
        "snapshot_at": at,
        "season": season,
        "week": week,
    }


def upsert_signals(
    signals: list[dict[str, Any]],
    *,
    bucket: str,
    captured_at: str | None = None,
    season: int | None = None,
    week: int | None = None,
    path: Path | None = None,
) -> dict[str, int]:
    """Merge pipeline rows into the shadow ledger (one row per event/side/bucket)."""
    ledger = load_ledger(path)
    index = {play_key(p.get("event_id"), p.get("side"), bucket=p.get("bucket") or ""): p for p in ledger["plays"]}
    at = captured_at or _now()
    added = 0
    updated = 0

    for s in signals:
        eid = str(s.get("event_id") or "")
        side = str(s.get("side") or "").lower()
        key = play_key(eid, side, bucket=bucket)
        snap = _snapshot_fields(s, at=at, season=season, week=week)
        away = s.get("away_team") or ""
        home = s.get("home_team") or ""

        if key in index:
            row = index[key]
            for field, val in snap.items():
                row[field] = val
            updated += 1
            continue

        row = {
            "id": str(uuid.uuid4())[:8],
            "event_id": eid,
            "game": f"{away}@{home}" if away and home else None,
            "away_team": away,
            "home_team": home,
            "kickoff": s.get("kickoff") or s.get("commence_time"),
            "market": "totals",
            "side": side,
            "bucket": bucket,
            "first_seen_at": at,
            "first_seen": dict(snap),
            **snap,
            "units": float(ledger.get("unit_stake") or 1.0),
            "status": "pending",
            "close_line": None,
            "close_price": None,
            "close_book": None,
            "clv_points": None,
            "clv_prob": None,
            "clv_at": None,
            "home_score": None,
            "away_score": None,
            "pnl_units": None,
            "settled_at": None,
            "pipeline": "ncaaf_totals_shadow",
        }
        ledger["plays"].append(row)
        index[key] = row
        added += 1

    save_ledger(ledger, path)
    return {"added": added, "updated": updated, "total": len(ledger["plays"])}
