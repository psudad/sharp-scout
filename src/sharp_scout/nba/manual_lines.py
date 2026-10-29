"""Apply hand-entered FanDuel (or other) game lines to the score-model paper store."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.nba.paths import NBA_MANUAL_LINES_PATH
from sharp_scout.nba.score_model.paper import (
    _find_game_by_matchup,
    _proj_row,
    load_paper_store,
    save_paper_store,
)
from sharp_scout.nba.score_model.state import ensure_score_engine
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.slate import ET

logger = logging.getLogger(__name__)

_AS_OF_ET_DATE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})\b",
    re.I,
)
_MONTH = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def load_manual_lines_raw(path: Path | None = None) -> dict[str, Any] | None:
    p = path or NBA_MANUAL_LINES_PATH
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        logger.warning("manual lines JSON invalid: %s", p)
        return None


def manual_lines_slate_date_et(doc: dict[str, Any]) -> date | None:
    """ET calendar date this manual file is intended for."""
    raw = doc.get("slate_date_et")
    if raw:
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            pass
    as_of = str(doc.get("as_of_et") or "")
    m = _AS_OF_ET_DATE.search(as_of)
    if not m:
        return None
    mon, day_s, year_s = m.group(1), m.group(2), m.group(3)
    month = _MONTH.get(mon[:3].lower())
    if month is None:
        return None
    return date(int(year_s), month, int(day_s))


def current_et_slate_date(now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ET).date()


def manual_lines_for_current_slate(
    doc: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> bool:
    if not doc or not doc.get("games"):
        return False
    slate = manual_lines_slate_date_et(doc)
    if slate is None:
        return False
    return slate == current_et_slate_date(now)


def load_manual_lines(path: Path | None = None, *, now: datetime | None = None) -> dict[str, Any] | None:
    doc = load_manual_lines_raw(path)
    if not manual_lines_for_current_slate(doc, now=now):
        return None
    return doc


def manual_lines_page_note(doc: dict[str, Any] | None = None, *, now: datetime | None = None) -> str:
    raw = doc if doc is not None else load_manual_lines_raw()
    if not manual_lines_for_current_slate(raw, now=now):
        return ""
    assert raw is not None
    source = str(raw.get("source") or "Manual")
    as_of = str(raw.get("as_of_et") or "").strip()
    if as_of:
        text = f"Supplemental {source} lines (manual entry) as of ~{as_of}."
    else:
        text = f"Supplemental {source} lines (manual entry) on this slate."
    return f'<p class="nba-section-note">{text}</p>'


def apply_manual_lines_to_paper_store(
    *,
    path: Path | None = None,
    store: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> int:
    """Append a scan per listed matchup with manual consensus lines (no Odds API)."""
    now = now or datetime.now(timezone.utc)
    doc = load_manual_lines(path, now=now)
    if not doc:
        return 0
    store = store or load_paper_store()
    at = now.isoformat()
    engine = ensure_score_engine()
    try:
        from sharp_scout.nba.score_model.injury_lag import load_store as load_injury_store

        injury_store = load_injury_store()
        prior_status = dict(injury_store.get("player_status") or {})
    except Exception:  # noqa: BLE001
        injury_store = {}
        prior_status = {}

    source = str(doc.get("source") or "manual")
    updated = 0
    for row in doc.get("games") or []:
        away = normalize_nba_team(str(row.get("away") or ""))
        home = normalize_nba_team(str(row.get("home") or ""))
        if not away or not home:
            continue
        g = _find_game_by_matchup(store, away, home, kickoff=row.get("kickoff"))
        if g is None:
            logger.warning("manual lines: no paper game for %s @ %s", away, home)
            continue
        scans = g.get("scans") or []
        if not scans:
            logger.warning("manual lines: no scans yet for %s @ %s", away, home)
            continue
        lines: dict[str, Any] = {
            "line_source": source,
            "manual_as_of_et": doc.get("as_of_et"),
        }
        if row.get("spread_home") is not None:
            lines["consensus_spread_home"] = float(row["spread_home"])
        if row.get("total") is not None:
            lines["consensus_total"] = float(row["total"])
        first_scan_at = scans[0].get("at")
        ev_row = {
            "event_id": g.get("event_id"),
            "home_team": home,
            "away_team": away,
            "commence_time": g.get("kickoff"),
        }
        snap = _proj_row(
            engine,
            ev_row,
            at=at,
            lines=lines,
            prior_status=prior_status,
            injury_store=injury_store,
            first_scan_at=first_scan_at,
        )
        snap["source"] = "manual_lines"
        from sharp_scout.nba.score_model.pace_v1 import pace_display_pick_from_snapshot, recommended_unit_fraction

        v1_pick = pace_display_pick_from_snapshot(snap, home=home, away=away, engine=engine)
        if v1_pick:
            snap["pace_v1_pick"] = v1_pick.get("pick")
            snap["pace_v1_gap"] = v1_pick.get("gap")
            snap["pace_v1_recommended_units"] = recommended_unit_fraction(
                snap, v1_pick, home=home, away=away, engine=engine
            )
        g["scans"].append(snap)
        if len(g["scans"]) > 40:
            g["scans"] = g["scans"][-40:]
        if v1_pick:
            g["pace_published_pick"] = v1_pick
        from sharp_scout.utils.kickoff import parse_kickoff_utc

        kick_dt = parse_kickoff_utc(g.get("kickoff"))
        if kick_dt:
            from sharp_scout.nba.score_model.totals_shadow import maybe_record_totals_shadow_for_scan

            maybe_record_totals_shadow_for_scan(
                engine,
                event_id=str(g.get("event_id") or ""),
                home=home,
                away=away,
                kickoff=kick_dt,
                scan_at=at,
                snap=snap,
            )
        updated += 1

    if updated:
        store["manual_lines"] = {
            "source": source,
            "as_of_et": doc.get("as_of_et"),
            "slate_date_et": manual_lines_slate_date_et(doc).isoformat()
            if manual_lines_slate_date_et(doc)
            else None,
            "applied_at": at,
            "path": str(path or NBA_MANUAL_LINES_PATH),
        }
        save_paper_store(store)
    return updated
