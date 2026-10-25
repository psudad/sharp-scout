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
from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

PAPER_PATH = DATA_DIR / "paper" / "nba_injury_lag.json"
IMPACT_MIN_PTS = 1.5
LINE_LAG_FRAC = 0.5
WATCH_STATUS = frozenset({"out", "doubtful"})


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "player_status": {}, "entries": [], "summary": {}}


def load_store(path: Any = None) -> dict[str, Any]:
    p = path or PAPER_PATH
    if not p.exists():
        return _empty_store()
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return _empty_store()
    raw.setdefault("player_status", {})
    raw.setdefault("entries", [])
    return raw


def save_store(store: dict[str, Any], path: Any = None) -> None:
    p = path or PAPER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")


def _load_player_impact_table() -> dict[str, float]:
    """player name lower -> estimated team pts impact when out."""
    path = nba_paths.NBA_PLAYER_RATES_PATH
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    rows = raw.get("players") if isinstance(raw.get("players"), list) else []
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("player_name") or row.get("name")
        ppm = row.get("pts_per_min")
        mins = row.get("minutes") or row.get("mpg") or 30
        if not name or ppm is None:
            continue
        try:
            impact = float(ppm) * float(mins)
        except (TypeError, ValueError):
            continue
        out[str(name).strip().lower()] = impact
    return out


def _player_impact(name: str, team: str, table: dict[str, float]) -> float:
    key = name.strip().lower()
    if key in table:
        return float(table[key])
    parts = key.split()
    if parts:
        last = parts[-1]
        hits = [v for k, v in table.items() if last in k]
        if len(hits) == 1:
            return float(hits[0])
    return 0.0


def _events_by_team(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for ev in events:
        for team in (ev.get("home_team"), ev.get("away_team")):
            if team:
                out[normalize_nba_team(str(team))] = ev
    return out


def _line_move_for_team(ev: dict[str, Any], team: str) -> tuple[float | None, float | None]:
    lines = snapshot_game_lines(ev)
    home = normalize_nba_team(str(ev.get("home_team") or ""))
    spread = lines.get("consensus_spread_home")
    total = lines.get("consensus_total")
    if spread is None:
        return None, total
    if team == home:
        return float(spread), total
    return -float(spread), total


def record_injury_lag_scan(events: list[dict[str, Any]], *, store: dict[str, Any] | None = None) -> int:
    """Detect new Out/Doubtful vs last scan; log paper leans when line hasn't moved enough."""
    store = store or load_store()
    now = datetime.now(timezone.utc).isoformat()
    try:
        injuries = fetch_espn_nba_injuries()
    except Exception as exc:  # noqa: BLE001
        logger.warning("injury lag: ESPN injuries unavailable (%s)", exc)
        return 0

    impact_table = _load_player_impact_table()
    team_events = _events_by_team(events)
    prev = store.get("player_status") or {}
    added = 0

    for row in injuries:
        name = str(row.get("player") or "").strip()
        team = normalize_nba_team(str(row.get("team") or ""))
        status = str(row.get("status") or "").strip().lower()
        if not name or not team:
            continue
        pkey = f"{team}|{name.lower()}"
        old = str(prev.get(pkey) or "").lower()
        prev[pkey] = status
        if status not in WATCH_STATUS:
            continue
        if old in WATCH_STATUS:
            continue
        impact = _player_impact(name, team, impact_table)
        if impact < IMPACT_MIN_PTS:
            continue
        ev = team_events.get(team)
        if not ev:
            continue
        spread, total = _line_move_for_team(ev, team)
        lines = snapshot_game_lines(ev)
        store["entries"].append(
            {
                "id": f"{pkey}|{now}",
                "detected_at": now,
                "player": name,
                "team": team,
                "status": status,
                "impact_pts": round(impact, 2),
                "event_id": ev.get("event_id"),
                "kickoff": ev.get("commence_time"),
                "line_at_detection": lines,
                "spread_team": spread,
                "expected_move_pts": round(impact * LINE_LAG_FRAC, 2),
                "graded": None,
            }
        )
        added += 1

    store["player_status"] = prev
    if added:
        save_store(store)
    else:
        save_store(store)
    return added


def grade_injury_lag_entries(store: dict[str, Any] | None = None) -> dict[str, Any]:
    """Grade logged leans vs closing line movement (from line history) and result."""
    from sharp_scout.data import line_store
    from sharp_scout.utils.kickoff import parse_kickoff_utc

    store = store or load_store()
    history = line_store.load_history(nba_paths.NBA_LINE_HISTORY_PATH)
    graded = 0
    for entry in store.get("entries") or []:
        if entry.get("graded"):
            continue
        eid = entry.get("event_id")
        if not eid:
            continue
        kick = parse_kickoff_utc(entry.get("kickoff"))
        if kick and kick > datetime.now(timezone.utc):
            continue
        det = parse_kickoff_utc(entry.get("detected_at"))
        open_lines = entry.get("line_at_detection") or {}
        close_spread = open_lines.get("consensus_spread_home")
        key = line_store.series_key(eid, "spreads", "home")
        samples = history.get(key) or []
        if samples:
            close_spread = samples[-1].get("line", close_spread)
        move = None
        if close_spread is not None and open_lines.get("consensus_spread_home") is not None:
            move = float(close_spread) - float(open_lines["consensus_spread_home"])
        entry["graded"] = {
            "graded_at": datetime.now(timezone.utc).isoformat(),
            "close_spread_home": close_spread,
            "spread_move": move,
            "lag_detected": move is not None
            and abs(move) < float(entry.get("expected_move_pts") or 0),
        }
        graded += 1

    store["summary"] = {
        "n_entries": len(store.get("entries") or []),
        "n_graded": sum(1 for e in store.get("entries") or [] if e.get("graded")),
        "n_lag_flagged": sum(
            1 for e in store.get("entries") or [] if (e.get("graded") or {}).get("lag_detected")
        ),
    }
    save_store(store)
    return store


def open_entries_for_page(store: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    store = store or load_store()
    return [e for e in store.get("entries") or [] if not e.get("graded")][-20:]
