"""ESPN NBA team box scores → possessions (research, free API)."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from sharp_scout.data.espn_cfb import _get_json
from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

ESPN_SUMMARY = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
ESPN_NBA_ABBREV: dict[str, str] = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "SA": "SAS",
    "UTAH": "UTA",
    "WSH": "WAS",
}

BOX_CACHE_VERSION = 1


def _team_code(team: dict[str, Any]) -> str:
    raw = team.get("abbreviation") or team.get("shortDisplayName") or ""
    code = str(raw).upper()
    code = ESPN_NBA_ABBREV.get(code, code)
    return normalize_nba_team(code)


def _parse_made_attempted(raw: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d+)\s*-\s*(\d+)", str(raw).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _stat_value(stats: list[dict[str, Any]], *names: str) -> str | None:
    for st in stats:
        nm = str(st.get("name") or st.get("label") or "").lower()
        for want in names:
            if want.lower() in nm:
                return st.get("displayValue") or st.get("value")
    return None


def parse_team_box(team_block: dict[str, Any]) -> dict[str, float]:
    stats = team_block.get("statistics") or []
    fga = oreb = tov = fta = 0
    fgm_pair = _parse_made_attempted(_stat_value(stats, "fieldGoalsMade-fieldGoalsAttempted") or "")
    if fgm_pair:
        _, fga = fgm_pair
    oreb_raw = _stat_value(stats, "offensiveRebounds")
    if oreb_raw is not None:
        oreb = int(float(oreb_raw))
    tov_raw = _stat_value(stats, "totalTurnovers", "turnovers")
    if tov_raw is not None:
        tov = int(float(tov_raw))
    ft_pair = _parse_made_attempted(_stat_value(stats, "freeThrowsMade-freeThrowsAttempted") or "")
    if ft_pair:
        _, fta = ft_pair
    poss = max(float(fga - oreb + tov + 0.44 * fta), 1.0)
    return {"fga": float(fga), "oreb": float(oreb), "tov": float(tov), "fta": float(fta), "poss": poss}


def parse_player_minutes_by_team(summary: dict[str, Any]) -> dict[str, dict[str, float]]:
    """team_code -> {player_name_lower: minutes}."""
    out: dict[str, dict[str, float]] = {}
    box = summary.get("boxscore") or {}
    for team_block in box.get("players") or []:
        team = _team_code((team_block.get("team") or {}))
        team_mins: dict[str, float] = {}
        for stat_group in team_block.get("statistics") or []:
            labels = [str(x).upper() for x in (stat_group.get("labels") or stat_group.get("names") or [])]
            min_idx = next((i for i, lb in enumerate(labels) if lb in ("MIN", "MINS", "MINUTES")), None)
            for ath in stat_group.get("athletes") or []:
                athlete = ath.get("athlete") or {}
                name = str(athlete.get("displayName") or athlete.get("shortName") or "").strip().lower()
                if not name or min_idx is None:
                    continue
                stats = ath.get("stats") or []
                if min_idx >= len(stats):
                    continue
                raw = str(stats[min_idx])
                mins = 0.0
                if ":" in raw:
                    parts = raw.split(":")
                    try:
                        mins = float(parts[0]) + float(parts[1]) / 60.0
                    except ValueError:
                        mins = 0.0
                else:
                    try:
                        mins = float(raw)
                    except ValueError:
                        mins = 0.0
                if mins > 0:
                    team_mins[name] = mins
        if team_mins:
            out[team] = team_mins
    return out


def fetch_event_box(event_id: str) -> dict[str, Any] | None:
    try:
        summary = _get_json(f"{ESPN_SUMMARY}?{urlencode({'event': event_id})}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("box fetch fail %s: %s", event_id, exc)
        return None
    if not isinstance(summary, dict):
        return None
    box = summary.get("boxscore") or {}
    teams = box.get("teams") or []
    if len(teams) < 2:
        return None
    by_team = parse_player_minutes_by_team(summary)
    parsed: dict[str, Any] = {}
    for tb in teams:
        code = _team_code(tb.get("team") or {})
        parsed[code] = parse_team_box(tb)
        parsed[code]["player_mins"] = by_team.get(code) or {}
    return parsed


def load_box_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": BOX_CACHE_VERSION, "events": {}}
    raw = json.loads(path.read_text())
    if raw.get("version") != BOX_CACHE_VERSION:
        return {"version": BOX_CACHE_VERSION, "events": {}}
    return raw


def ensure_box_scores(
    event_ids: list[str],
    cache_path: Path,
    *,
    sleep_s: float = 0.05,
    max_fetch: int | None = None,
) -> dict[str, dict[str, Any]]:
    cache = load_box_cache(cache_path)
    events: dict[str, Any] = cache.setdefault("events", {})
    todo = [eid for eid in event_ids if eid and eid not in events]
    if max_fetch is not None:
        todo = todo[:max_fetch]
    for i, eid in enumerate(todo):
        row = fetch_event_box(str(eid))
        if row:
            events[str(eid)] = row
        if sleep_s and (i + 1) % 50 == 0:
            time.sleep(sleep_s)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache))
    return events


def attach_box_stats_to_games(games: list[dict[str, Any]], events: dict[str, dict[str, Any]]) -> None:
    for g in games:
        eid = g.get("event_id")
        if not eid:
            continue
        box = events.get(str(eid))
        if not box:
            continue
        home, away = g["home"], g["away"]
        hb, ab = box.get(home), box.get(away)
        if not hb or not ab:
            continue
        g["home_poss"] = hb["poss"]
        g["away_poss"] = ab["poss"]
        g["game_poss"] = (hb["poss"] + ab["poss"]) / 2.0
        g["home_player_mins"] = (hb.get("player_mins") or {}) if hb else {}
        g["away_player_mins"] = (ab.get("player_mins") or {}) if ab else {}


def estimate_poss_from_points(hs: float, as_: float) -> float:
    return max((hs + as_) / 2.2, 90.0)
