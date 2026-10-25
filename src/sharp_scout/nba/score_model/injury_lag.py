"""Paper-track injury news vs line movement (ESPN injuries, no Odds API)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.data.espn_nba import fetch_espn_nba_injuries
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.score_model.lines import snapshot_game_lines
from sharp_scout.nba.score_model.player_impact import (
    bpm_proxy_per100,
    lookup_player_row,
    load_rates_by_team_player,
    margin_impact_pts,
)
from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

PAPER_PATH = DATA_DIR / "paper" / "nba_injury_lag.json"
IMPACT_MIN_PTS = 1.5
LINE_LAG_FRAC = 0.5
WATCH_STATUS = frozenset({"out", "doubtful"})
PRIOR_ELIGIBLE = frozenset({"available", "questionable", "day-to-day", "probable", "active"})


def _empty_store() -> dict[str, Any]:
    return {
        "version": 2,
        "player_status": {},
        "player_watch_streak": {},
        "last_scan_lines": {},
        "entries": [],
        "summary": {},
    }


def load_store(path: Any = None) -> dict[str, Any]:
    p = path or PAPER_PATH
    if not p.exists():
        return _empty_store()
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return _empty_store()
    raw.setdefault("player_status", {})
    raw.setdefault("player_watch_streak", {})
    raw.setdefault("last_scan_lines", {})
    raw.setdefault("entries", [])
    return raw


def save_store(store: dict[str, Any], path: Any = None) -> None:
    p = path or PAPER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")


def normalize_injury_status(raw: str) -> str:
    s = str(raw or "").lower().strip()
    if not s:
        return "unknown"
    if "out" in s:
        return "out"
    if "doubt" in s:
        return "doubtful"
    if "question" in s:
        return "questionable"
    if "day" in s and "day" in s.replace("-", " "):
        return "day-to-day"
    if "prob" in s:
        return "probable"
    if "avail" in s or "active" in s:
        return "available"
    return s


def _events_by_team(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for ev in events:
        for team in (ev.get("home_team"), ev.get("away_team")):
            if team:
                out[normalize_nba_team(str(team))] = ev
    return out


def _spread_move_since_prior(
    lines_now: dict[str, float | None],
    lines_prior: dict[str, float | None],
) -> float | None:
    if lines_now.get("consensus_spread_home") is None or lines_prior.get("consensus_spread_home") is None:
        return None
    return float(lines_now["consensus_spread_home"]) - float(lines_prior["consensus_spread_home"])


def _line_lag_at_detection(
    lines_now: dict[str, float | None],
    lines_prior: dict[str, float | None],
    *,
    expected_move: float,
) -> bool:
    """True when market has not moved ~half the expected margin impact since prior scan."""
    move = _spread_move_since_prior(lines_now, lines_prior)
    if move is None:
        return False
    return abs(move) < expected_move


def record_injury_lag_scan(events: list[dict[str, Any]], *, store: dict[str, Any] | None = None) -> int:
    """Log leans only on eligible status transitions with prior-scan lines and insufficient line move."""
    store = store or load_store()
    now = datetime.now(timezone.utc).isoformat()
    try:
        injuries = fetch_espn_nba_injuries()
    except Exception as exc:  # noqa: BLE001
        logger.warning("injury lag: ESPN injuries unavailable (%s)", exc)
        injuries = []
    # Always refresh prior-scan line snapshot for next run (even if injury feed empty).

    rates = load_rates_by_team_player()
    team_events = _events_by_team(events)
    prev_status: dict[str, str] = dict(store.get("player_status") or {})
    watch_streak: dict[str, int] = dict(store.get("player_watch_streak") or {})
    prior_scan_lines: dict[str, Any] = dict(store.get("last_scan_lines") or {})
    added = 0

    for row in injuries:
        name = str(row.get("player") or "").strip()
        team = normalize_nba_team(str(row.get("team") or ""))
        status = normalize_injury_status(row.get("status"))
        if not name or not team:
            continue
        pkey = f"{team}|{name.lower()}"
        old = prev_status.get(pkey)

        if old is None:
            prev_status[pkey] = status
            if status in WATCH_STATUS:
                watch_streak[pkey] = 1
            continue

        if status in WATCH_STATUS:
            if old in WATCH_STATUS:
                watch_streak[pkey] = watch_streak.get(pkey, 1) + 1
                prev_status[pkey] = status
                continue
            if old not in PRIOR_ELIGIBLE:
                prev_status[pkey] = status
                if status in WATCH_STATUS:
                    watch_streak[pkey] = 1
                continue

            rate_row = lookup_player_row(name, team, rates)
            if rate_row is None:
                prev_status[pkey] = status
                watch_streak[pkey] = 1
                continue
            impact = margin_impact_pts(rate_row)
            if impact < IMPACT_MIN_PTS:
                prev_status[pkey] = status
                watch_streak[pkey] = 1
                continue

            ev = team_events.get(team)
            if not ev:
                prev_status[pkey] = status
                watch_streak[pkey] = 1
                continue
            eid = str(ev.get("event_id") or "")
            lines_now = snapshot_game_lines(ev)
            lines_before = prior_scan_lines.get(eid)
            if not lines_before:
                prev_status[pkey] = status
                watch_streak[pkey] = 1
                continue

            expected = impact * LINE_LAG_FRAC
            if not _line_lag_at_detection(lines_now, lines_before, expected_move=expected):
                prev_status[pkey] = status
                watch_streak[pkey] = 1
                continue

            store["entries"].append(
                {
                    "id": f"{pkey}|{now}",
                    "detected_at": now,
                    "player": name,
                    "team": team,
                    "status": status,
                    "prior_status": old,
                    "impact_pts": round(impact, 2),
                    "bpm_proxy": round(bpm_proxy_per100(rate_row), 2),
                    "event_id": eid,
                    "kickoff": ev.get("commence_time"),
                    "line_at_prior_scan": lines_before,
                    "line_at_detection": lines_now,
                    "spread_move_since_prior": _spread_move_since_prior(lines_now, lines_before),
                    "expected_move_pts": round(expected, 2),
                    "graded": None,
                }
            )
            added += 1
            prev_status[pkey] = status
            watch_streak[pkey] = 1
            continue

        prev_status[pkey] = status
        watch_streak[pkey] = 0

    store["player_status"] = prev_status
    store["player_watch_streak"] = watch_streak
    store["last_scan_lines"] = {
        str(ev.get("event_id")): snapshot_game_lines(ev)
        for ev in events
        if ev.get("event_id")
    }
    save_store(store)
    return added


def grade_injury_lag_entries(store: dict[str, Any] | None = None) -> dict[str, Any]:
    """Grade logged leans vs closing line movement (from line history)."""
    from sharp_scout.data import line_store
    from sharp_scout.utils.kickoff import parse_kickoff_utc

    store = store or load_store()
    history = line_store.load_history(nba_paths.NBA_LINE_HISTORY_PATH)
    for entry in store.get("entries") or []:
        if entry.get("graded"):
            continue
        eid = entry.get("event_id")
        if not eid:
            continue
        kick = parse_kickoff_utc(entry.get("kickoff"))
        if kick and kick > datetime.now(timezone.utc):
            continue
        det_lines = entry.get("line_at_detection") or {}
        prior_lines = entry.get("line_at_prior_scan") or {}
        close_spread = det_lines.get("consensus_spread_home")
        key = line_store.series_key(eid, "spreads", "home")
        samples = history.get(key) or []
        if samples:
            close_spread = samples[-1].get("line", close_spread)
        move_prior_to_det = entry.get("spread_move_since_prior")
        move_det_to_close = None
        if close_spread is not None and det_lines.get("consensus_spread_home") is not None:
            move_det_to_close = float(close_spread) - float(det_lines["consensus_spread_home"])
        entry["graded"] = {
            "graded_at": datetime.now(timezone.utc).isoformat(),
            "close_spread_home": close_spread,
            "move_prior_to_detection": move_prior_to_det,
            "move_detection_to_close": move_det_to_close,
            "lag_at_detection": move_prior_to_det is not None
            and abs(float(move_prior_to_det)) < float(entry.get("expected_move_pts") or 0),
        }

    store["summary"] = {
        "n_entries": len(store.get("entries") or []),
        "n_graded": sum(1 for e in store.get("entries") or [] if e.get("graded")),
        "n_lag_flagged": sum(
            1 for e in store.get("entries") or [] if (e.get("graded") or {}).get("lag_at_detection")
        ),
    }
    save_store(store)
    return store


def open_entries_for_page(store: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    store = store or load_store()
    return [e for e in store.get("entries") or [] if not e.get("graded")][-20:]
