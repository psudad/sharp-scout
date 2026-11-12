"""Persist NCAAM price-edge shadow diagnostics (never the official ledger)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR

SHADOW_PATH = DATA_DIR / "shadow" / "ncaam_price_edge_diagnostics.json"


def record_price_edge_batch(
    rows: list[dict[str, Any]],
    *,
    gate_enabled: bool,
    min_edge: float,
    path: Path | None = None,
) -> Path:
    """Merge this run's candidate rows into the shadow diagnostics file."""
    dest = path or SHADOW_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any]
    if dest.exists():
        try:
            payload = json.loads(dest.read_text())
        except (OSError, ValueError):
            payload = {}
    else:
        payload = {}
    entries: list[dict[str, Any]] = list(payload.get("entries") or [])
    seen = {
        (
            str(e.get("espn_id") or ""),
            str(e.get("market") or ""),
            str(e.get("side") or ""),
            str(e.get("locked_at") or e.get("recorded_at") or ""),
        )
        for e in entries
    }
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        key = (
            str(row.get("espn_id") or ""),
            str(row.get("market") or ""),
            str(row.get("side") or ""),
            str(row.get("locked_at") or now),
        )
        if key in seen:
            continue
        entries.append({**row, "recorded_at": now})
        seen.add(key)
    payload.update(
        {
            "updated_at": now,
            "gate_enabled": gate_enabled,
            "min_edge": min_edge,
            "entries": entries[-500:],
        }
    )
    dest.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return dest
