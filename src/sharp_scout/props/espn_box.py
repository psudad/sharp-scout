"""ESPN box-score fallback for prop settlement.

nflverse play-by-play lags behind final whistles (sometimes by a day), which leaves graded
games stuck pending. ESPN publishes final box scores within minutes, so when PBP has not
caught up we resolve the stat line from there.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sharp_scout.data.espn_cfb import _FINAL_STATUSES, _get_json
from sharp_scout.props.usage import _player_key
from sharp_scout.utils.odds import normalize_team
from sharp_scout.utils.slate import parse_commence

logger = logging.getLogger(__name__)

SCOREBOARD = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SUMMARY = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/summary"


_ZERO_STATS = (
    "receptions", "receiving_yards", "receiving_tds", "carries", "rushing_yards",
    "rushing_tds", "attempts", "passing_yards", "passing_tds",
)


def _num(x: Any) -> float:
    try:
        return float(str(x).split("/")[-1] if "/" in str(x) and "-" not in str(x)[:1] else x)
    except (TypeError, ValueError):
        return 0.0


def parse_boxscore(summary: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Normalized player name -> stat dict using nflverse-style column names."""
    out: dict[str, dict[str, float]] = {}
    for team in (summary.get("boxscore") or {}).get("players") or []:
        for cat in team.get("statistics") or []:
            name = cat.get("name")
            keys = cat.get("keys") or []
            for a in cat.get("athletes") or []:
                pk = _player_key((a.get("athlete") or {}).get("displayName") or "")
                vals = dict(zip(keys, a.get("stats") or []))
                # A player on the box score who has no line in a category recorded zero.
                row = out.setdefault(pk, dict.fromkeys(_ZERO_STATS, 0.0))
                if name == "receiving":
                    row["receptions"] = _num(vals.get("receptions"))
                    row["receiving_yards"] = _num(vals.get("receivingYards"))
                    row["receiving_tds"] = _num(vals.get("receivingTouchdowns"))
                elif name == "rushing":
                    row["carries"] = _num(vals.get("rushingAttempts"))
                    row["rushing_yards"] = _num(vals.get("rushingYards"))
                    row["rushing_tds"] = _num(vals.get("rushingTouchdowns"))
                elif name == "passing":
                    att = str(vals.get("completions/passingAttempts") or "0/0").split("/")[-1]
                    row["attempts"] = _num(att)
                    row["passing_yards"] = _num(vals.get("passingYards"))
                    row["passing_tds"] = _num(vals.get("passingTouchdowns"))
    for row in out.values():
        row["anytime_td"] = 1.0 if row.get("receiving_tds", 0) + row.get("rushing_tds", 0) >= 1 else 0.0
    return out


class EspnBox:
    def __init__(self) -> None:
        self._events: dict[str, tuple[str, bool]] = {}  # "AWAY@HOME|YYYYMMDD" -> (id, final)
        self._boxes: dict[str, dict[str, dict[str, float]]] = {}
        self._days: set[str] = set()

    def _load_day(self, day: str) -> None:
        if day in self._days:
            return
        self._days.add(day)
        try:
            payload = _get_json(f"{SCOREBOARD}?dates={day}&limit=200")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESPN scoreboard %s failed: %s", day, exc)
            return
        for ev in (payload or {}).get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            status = ((comp.get("status") or {}).get("type") or {}).get("name") or ""
            home = away = ""
            for c in comp.get("competitors") or []:
                code = normalize_team(str((c.get("team") or {}).get("abbreviation") or ""), "nfl")
                if c.get("homeAway") == "home":
                    home = code
                else:
                    away = code
            if home and away:
                self._events[f"{away}@{home}|{day}"] = (str(ev.get("id")), status in _FINAL_STATUSES)

    def stats_for(self, play: dict[str, Any]) -> tuple[str, dict[str, float] | None]:
        """('ok', stat row) | ('void', None) player absent from a final box | ('unknown', None)."""
        kick = parse_commence(play.get("kickoff") or play.get("commence_time"))
        if kick is None:
            return "unknown", None
        base = kick.astimezone(timezone.utc)
        key = f"{play.get('away_team')}@{play.get('home_team')}"
        for delta in (0, -1, 1):
            day = (base + timedelta(days=delta)).strftime("%Y%m%d")
            self._load_day(day)
            hit = self._events.get(f"{key}|{day}")
            if not hit:
                continue
            eid, final = hit
            if not final:
                return "unknown", None
            if eid not in self._boxes:
                try:
                    self._boxes[eid] = parse_boxscore(_get_json(f"{SUMMARY}?event={eid}") or {})
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ESPN box %s failed: %s", eid, exc)
                    return "unknown", None
            box = self._boxes[eid]
            if not box:
                return "unknown", None
            row = box.get(_player_key(str(play.get("player_name") or "")))
            return ("ok", row) if row else ("void", None)
        return "unknown", None
