"""Load committed Action Network split snapshots from data/paper/nba_sharp_splits/."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR
from sharp_scout.nba.sharp_splits.nicknames import team_code_from_snapshot_label
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc

ET = ZoneInfo("America/New_York")
SPLITS_DIR = DATA_DIR / "paper" / "nba_sharp_splits"
_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{4})\.json$")


def _parse_pulled_at(raw: str | None, path: Path) -> datetime | None:
    if raw:
        dt = parse_kickoff_utc(raw)
        if dt is not None:
            return dt
    m = _FILENAME_RE.match(path.name)
    if not m:
        return None
    day, hm = m.group(1), m.group(2)
    try:
        return datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H%M").replace(tzinfo=ET)
    except ValueError:
        return None


def load_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    pulled = _parse_pulled_at(str(raw.get("pulled_at") or ""), path)
    if pulled is None:
        return None
    game_date = str(raw.get("game_date") or "")
    if not game_date and _FILENAME_RE.match(path.name):
        game_date = _FILENAME_RE.match(path.name).group(1)  # type: ignore[union-attr]
    games: list[dict[str, Any]] = []
    for g in raw.get("games") or []:
        away = team_code_from_snapshot_label(str(g.get("away") or ""))
        home = team_code_from_snapshot_label(str(g.get("home") or ""))
        games.append(
            {
                "away": away,
                "home": home,
                "tip_et": g.get("tip_et"),
                "spread": g.get("spread"),
                "total": g.get("total"),
                "ml": g.get("ml"),
            }
        )
    return {
        "path": str(path),
        "pulled_at": pulled,
        "game_date": game_date,
        "games": games,
    }


def list_snapshots(*, splits_dir: Path | None = None) -> list[dict[str, Any]]:
    root = splits_dir or SPLITS_DIR
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if path.name.lower() == "readme.md":
            continue
        snap = load_snapshot(path)
        if snap:
            out.append(snap)
    out.sort(key=lambda s: s["pulled_at"])
    return out


def kickoff_game_date_et(kickoff: Any) -> date | None:
    dt = parse_kickoff_utc(kickoff)
    if dt is None:
        return None
    return dt.astimezone(ET).date()


def _game_key(away: str, home: str) -> tuple[str, str]:
    a = normalize_nba_team(away)
    h = normalize_nba_team(home)
    return (a, h)


def find_game_splits(
    *,
    away_team: str,
    home_team: str,
    kickoff: Any,
    snapshots: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, datetime | None]:
    """Latest snapshot before tip that includes this matchup on the kickoff's ET slate date."""
    snaps = snapshots if snapshots is not None else list_snapshots()
    kick_dt = parse_kickoff_utc(kickoff)
    if kick_dt is None:
        return None, None
    slate = kickoff_game_date_et(kickoff)
    if slate is None:
        return None, None
    key = _game_key(away_team, home_team)
    best_game: dict[str, Any] | None = None
    best_pulled: datetime | None = None
    for snap in snaps:
        pulled: datetime = snap["pulled_at"]
        if pulled >= kick_dt:
            continue
        gd = snap.get("game_date")
        try:
            snap_day = datetime.strptime(str(gd), "%Y-%m-%d").date() if gd else None
        except ValueError:
            snap_day = None
        if snap_day is not None and snap_day != slate:
            continue
        for g in snap.get("games") or []:
            if (g.get("away"), g.get("home")) != key:
                continue
            if best_pulled is None or pulled > best_pulled:
                best_pulled = pulled
                best_game = g
    return best_game, best_pulled
