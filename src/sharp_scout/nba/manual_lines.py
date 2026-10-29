"""Apply hand-entered FanDuel (or other) game lines to the score-model paper store."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
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

logger = logging.getLogger(__name__)


def load_manual_lines(path: Path | None = None) -> dict[str, Any] | None:
    p = path or NBA_MANUAL_LINES_PATH
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        logger.warning("manual lines JSON invalid: %s", p)
        return None
    if not raw.get("games"):
        return None
    return raw


def manual_lines_page_note(doc: dict[str, Any] | None = None) -> str:
    doc = doc if doc is not None else load_manual_lines()
    if not doc:
        return ""
    source = str(doc.get("source") or "Manual")
    as_of = str(doc.get("as_of_et") or "").strip()
    if as_of:
        text = (
            f"Tonight&apos;s market lines are {source} as of ~{as_of} "
            "(manual entry; Odds API scan paused)."
        )
    else:
        text = f"Tonight&apos;s market lines are {source} (manual entry; Odds API scan paused)."
    return f'<p class="nba-section-note">{text}</p>'


def apply_manual_lines_to_paper_store(
    *,
    path: Path | None = None,
    store: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> int:
    """Append a scan per listed matchup with manual consensus lines (no Odds API)."""
    doc = load_manual_lines(path)
    if not doc:
        return 0
    store = store or load_paper_store()
    now = now or datetime.now(timezone.utc)
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
        updated += 1

    if updated:
        store["manual_lines"] = {
            "source": source,
            "as_of_et": doc.get("as_of_et"),
            "applied_at": at,
            "path": str(path or NBA_MANUAL_LINES_PATH),
        }
        save_paper_store(store)
    return updated
