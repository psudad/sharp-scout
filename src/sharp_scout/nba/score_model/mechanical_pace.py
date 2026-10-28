"""Mechanical Pace v1 qualifications (separate from Jason's official card)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.nba.slate_et import kickoff_date_et

MECHANICAL_PATH = DATA_DIR / "paper" / "nba_pace_mechanical.json"
MECHANICAL_CSV_PATH = DATA_DIR / "paper" / "nba_pace_mechanical.csv"


def load_mechanical_pace(path: Path | None = None) -> dict[str, Any]:
    p = path or MECHANICAL_PATH
    if not p.exists():
        return {"version": 1, "plays": [], "updated_at": None}
    raw = json.loads(p.read_text())
    raw.setdefault("plays", [])
    return raw


def save_mechanical_pace(store: dict[str, Any], path: Path | None = None) -> None:
    p = path or MECHANICAL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")
    _write_csv(store)


def _write_csv(store: dict[str, Any]) -> None:
    fields = [
        "id",
        "date_et",
        "away",
        "home",
        "market",
        "pick",
        "gap_pts",
        "result",
        "clv_toward_model",
        "model_error_vs_close",
        "recommended_units",
        "on_official_card",
    ]
    with MECHANICAL_CSV_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in store.get("plays") or []:
            w.writerow({k: r.get(k) for k in fields})


def _slot_key(date_et: str, away: str, home: str, market: str) -> tuple[str, str, str, str]:
    return (date_et, away, home, market)


def log_mechanical_play(entry: dict[str, Any], *, store: dict[str, Any] | None = None) -> bool:
    store = store or load_mechanical_pace()
    slot = _slot_key(
        str(entry.get("date_et") or ""),
        str(entry.get("away") or ""),
        str(entry.get("home") or ""),
        str(entry.get("market") or ""),
    )
    for p in store.get("plays") or []:
        if _slot_key(
            str(p.get("date_et") or ""),
            str(p.get("away") or ""),
            str(p.get("home") or ""),
            str(p.get("market") or ""),
        ) == slot:
            return False
    store.setdefault("plays", []).append(entry)
    save_mechanical_pace(store)
    return True


def upsert_mechanical_from_graded_game(
    g: dict[str, Any],
    *,
    pick: dict[str, Any],
    result: str,
    clv: dict[str, Any] | None = None,
    recommended_units: float = 1.0,
    on_official_card: bool = False,
) -> None:
    day = kickoff_date_et(g.get("kickoff"))
    entry = {
        "id": f"mech-{g.get('event_id')}-{pick.get('kind')}",
        "date_et": day.isoformat() if day else None,
        "kickoff": g.get("kickoff"),
        "away": g.get("away"),
        "home": g.get("home"),
        "market": pick.get("kind"),
        "pick": pick.get("pick"),
        "gap_pts": round(float(pick.get("gap") or 0), 2),
        "result": result,
        "recommended_units": recommended_units,
        "on_official_card": on_official_card,
    }
    if clv:
        entry.update(clv)
    log_mechanical_play(entry)
