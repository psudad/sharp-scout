"""Join ESPN slate to Odds API event ids."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.ncaam.espn import fetch_scoreboard_et_day
from sharp_scout.ncaam.teams import normalize_ncaam, torvik_teams
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

NCAAM_DATA = DATA_DIR / "ncaam"


def _match_odds_event(espn_row: dict[str, Any], odds_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    home = normalize_ncaam(espn_row.get("home_location") or "") or espn_row.get("home_team")
    away = normalize_ncaam(espn_row.get("away_location") or "") or espn_row.get("away_team")
    tip = espn_row.get("commence_time")
    for ev in odds_events:
        eh = ev.get("home_team")
        ea = ev.get("away_team")
        if {eh, ea} != {home, away}:
            continue
        if tip and ev.get("commence_time"):
            delta = abs((ev["commence_time"] - tip).total_seconds())
            if delta > 7200:
                continue
        return ev
    return None


def build_slate(
    *,
    et_day: date,
    odds_events: list[dict[str, Any]] | None = None,
    espn_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    espn_rows = espn_rows if espn_rows is not None else fetch_scoreboard_et_day(et_day)
    canon = torvik_teams()
    out: list[dict[str, Any]] = []
    for row in espn_rows:
        ht = normalize_ncaam(row.get("home_location") or "")
        at = normalize_ncaam(row.get("away_location") or "")
        if not ht or not at:
            continue
        if canon and (ht not in canon or at not in canon):
            continue
        merged = {**row, "home_team": ht, "away_team": at}
        if odds_events is not None:
            hit = _match_odds_event(row, odds_events)
            if hit:
                merged["odds_event_id"] = hit.get("event_id")
                merged["commence_time"] = hit.get("commence_time") or merged.get("commence_time")
        out.append(merged)
    return out


def save_slate(rows: list[dict[str, Any]], *, et_day: date) -> Path:
    path = NCAAM_DATA / f"slate_{et_day.strftime('%Y%m%d')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        if isinstance(row.get("commence_time"), datetime):
            row["commence_time"] = row["commence_time"].isoformat()
        serializable.append(row)
    path.write_text(json.dumps(serializable, indent=2, default=str) + "\n")
    return path


def load_demo_slate(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text())
    for row in raw:
        ct = row.get("commence_time")
        if isinstance(ct, str):
            row["commence_time"] = datetime.fromisoformat(ct.replace("Z", "+00:00"))
    return raw
