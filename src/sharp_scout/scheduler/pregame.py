"""Pregame window scheduler — fire at T-12h, T-3h, T-1h before kickoff."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR, get_settings
from sharp_scout.data.odds_api import OddsClient, mock_odds_events
from sharp_scout.utils.odds import setup_logging

logger = logging.getLogger(__name__)

STATE_PATH = DATA_DIR / "schedule_state.json"


@dataclass
class WindowHit:
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    window_hours: float
    hours_to_kick: float
    state_key: str


def load_state(path: Path | None = None) -> dict[str, Any]:
    p = path or STATE_PATH
    if not p.exists():
        return {"fired": {}}
    return json.loads(p.read_text())


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    p = path or STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(state, indent=2) + "\n")


def hours_until(commence: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if commence.tzinfo is None:
        commence = commence.replace(tzinfo=timezone.utc)
    return (commence - now).total_seconds() / 3600.0


def find_due_windows(
    events: list[dict[str, Any]],
    *,
    windows_hours: list[float] | None = None,
    tolerance_minutes: int | None = None,
    now: datetime | None = None,
    state: dict[str, Any] | None = None,
) -> list[WindowHit]:
    """Return events that fall inside a pregame window and have not yet fired."""
    settings = get_settings()
    windows = windows_hours or settings.pregame_windows
    tol_h = (tolerance_minutes if tolerance_minutes is not None else settings.pregame_window_tolerance_minutes) / 60.0
    now = now or datetime.now(timezone.utc)
    state = state or load_state()
    fired = state.get("fired") or {}

    hits: list[WindowHit] = []
    for ev in events:
        commence = ev.get("commence_time")
        if commence is None:
            continue
        if isinstance(commence, str):
            commence = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        if commence.tzinfo is None:
            commence = commence.replace(tzinfo=timezone.utc)
        htk = hours_until(commence, now)
        if htk < -0.25:
            continue  # already started / finished
        eid = str(ev.get("event_id"))
        for w in windows:
            # Inside [w - tol, w + tol]
            if abs(htk - w) <= tol_h:
                key = f"{eid}|T-{w:g}h"
                if key in fired:
                    continue
                hits.append(
                    WindowHit(
                        event_id=eid,
                        home_team=ev.get("home_team", ""),
                        away_team=ev.get("away_team", ""),
                        commence_time=commence,
                        window_hours=w,
                        hours_to_kick=htk,
                        state_key=key,
                    )
                )
    return hits


def mark_fired(hits: list[WindowHit], path: Path | None = None) -> dict[str, Any]:
    state = load_state(path)
    fired = state.setdefault("fired", {})
    now = datetime.now(timezone.utc).isoformat()
    for h in hits:
        fired[h.state_key] = {
            "fired_at": now,
            "event_id": h.event_id,
            "window_hours": h.window_hours,
            "matchup": f"{h.away_team}@{h.home_team}",
        }
    # Prune entries older than 14 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    keep = {}
    for k, v in fired.items():
        try:
            ts = datetime.fromisoformat(v["fired_at"])
            if ts >= cutoff:
                keep[k] = v
        except Exception:  # noqa: BLE001
            keep[k] = v
    state["fired"] = keep
    save_state(state, path)
    return state


def run_due_pregame(
    *,
    demo: bool = False,
    force_all_upcoming: bool = False,
    build_pages: bool = True,
    skip_pbp: bool = False,
) -> dict[str, Any]:
    """Check schedule; for each due window run side + props pipelines for that game."""
    settings = get_settings()
    setup_logging(settings.log_level)

    if demo or not settings.odds_api_key:
        events = mock_odds_events()
        # Force demo event into a due window for testing
        for ev in events:
            ev["commence_time"] = datetime.now(timezone.utc) + timedelta(hours=3)
            ev["pregame_window"] = 3.0
        hits = find_due_windows(events, state=load_state())
    else:
        client = OddsClient()
        try:
            events = client.fetch_events()
            if not events:
                events = client.fetch_odds()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load events: %s", exc)
            return {"ok": False, "error": str(exc), "hits": []}
        if force_all_upcoming:
            hits = [
                WindowHit(
                    event_id=str(e["event_id"]),
                    home_team=e["home_team"],
                    away_team=e["away_team"],
                    commence_time=e["commence_time"]
                    if isinstance(e["commence_time"], datetime)
                    else datetime.now(timezone.utc) + timedelta(hours=12),
                    window_hours=-1,
                    hours_to_kick=hours_until(
                        e["commence_time"]
                        if isinstance(e["commence_time"], datetime)
                        else datetime.now(timezone.utc)
                    ),
                    state_key=f"{e['event_id']}|manual",
                )
                for e in events
                if e.get("commence_time")
            ]
        else:
            hits = find_due_windows(events)

    if not hits:
        logger.info("No pregame windows due")
        return {"ok": True, "hits": [], "ran": False}

    logger.info("Due windows: %s", [h.state_key for h in hits])
    due_ids = {h.event_id for h in hits}
    window_map = {h.event_id: h.window_hours for h in hits}

    # Full side odds for due games
    from sharp_scout.pipeline.run import run_pipeline
    from sharp_scout.props.pipeline import run_props_pipeline

    if demo or not settings.odds_api_key:
        side = run_pipeline(demo=True, skip_pbp=True, update_ledger=True, build_pages=False)
        # Annotate window on plays
        for p in side.get("plays") or []:
            p["window"] = window_map.get(str(p.get("event_id")), 3.0)
            p["pregame_window"] = p["window"]
        props = run_props_pipeline(demo=True, skip_pbp=True, update_ledger=True, build_pages=build_pages)
    else:
        client = OddsClient()
        all_odds = client.fetch_odds()
        due_events = []
        for ev in all_odds:
            if str(ev.get("event_id")) in due_ids:
                ev = dict(ev)
                ev["pregame_window"] = window_map.get(str(ev.get("event_id")))
                due_events.append(ev)

        # Side pipeline currently runs all events; filter afterward for ledger
        side = run_pipeline(demo=False, skip_pbp=skip_pbp, update_ledger=False, build_pages=False)
        # Only ledger plays for due events
        due_side = [p for p in (side.get("plays") or []) if str(p.get("event_id")) in due_ids]
        for p in due_side:
            p["window"] = window_map.get(str(p.get("event_id")))
            p["pregame_window"] = p["window"]
        if due_side:
            from sharp_scout.ledger.tracker import append_signals

            append_signals(due_side)

        # Props for due events only
        prop_events = []
        for ev in due_events:
            try:
                pev = client.fetch_event_props(str(ev["event_id"]))
                books = dict(ev.get("bookmakers") or {})
                for bk, bm in (pev.get("bookmakers") or {}).items():
                    if bk not in books:
                        books[bk] = bm
                    else:
                        mk = dict(books[bk].get("markets") or {})
                        mk.update(bm.get("markets") or {})
                        books[bk] = {**books[bk], "markets": mk}
                ev = dict(ev)
                ev["bookmakers"] = books
                prop_events.append(ev)
            except Exception as exc:  # noqa: BLE001
                logger.warning("prop odds %s: %s", ev.get("event_id"), exc)

        game_context = {
            str(g["event_id"]): {
                "home_spread": g.get("model_spread", 0),
                "total": g.get("model_total", 45),
            }
            for g in (side.get("games") or [])
            if str(g.get("event_id")) in due_ids
        }
        props = run_props_pipeline(
            demo=False,
            skip_pbp=skip_pbp,
            events=prop_events or None,
            update_ledger=True,
            build_pages=build_pages,
            game_context=game_context,
        )

    mark_fired(hits)
    return {
        "ok": True,
        "ran": True,
        "hits": [
            {
                "event_id": h.event_id,
                "matchup": f"{h.away_team}@{h.home_team}",
                "window_hours": h.window_hours,
                "hours_to_kick": round(h.hours_to_kick, 2),
                "state_key": h.state_key,
            }
            for h in hits
        ],
        "side_plays": len(side.get("plays") or []),
        "prop_plays": len(props.get("plays") or []),
    }