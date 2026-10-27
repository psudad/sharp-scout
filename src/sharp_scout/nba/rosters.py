"""ESPN roster lookups for NBA prop ↔ team validation (free API, cached per run)."""

from __future__ import annotations

import logging
from typing import Any

from sharp_scout.data.espn_cfb import _get_json
from sharp_scout.nba.franchises import is_nba_franchise
from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

ESPN_NBA_TEAMS = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
ESPN_NBA_ROSTER = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
# ESPN season year for 2026-27 (end year on roster/stat endpoints).
ESPN_NBA_SEASON_END_YEAR = 2027

_team_id_by_code: dict[str, str] | None = None
_roster_cache: dict[tuple[str, int], set[str]] = {}
_player_team_map_cache: dict[int, dict[str, str]] = {}


def roster_norm_name(name: str) -> str:
    return " ".join((name or "").lower().split())


def _norm_name(name: str) -> str:
    return roster_norm_name(name)


def _load_team_ids() -> dict[str, str]:
    global _team_id_by_code
    if _team_id_by_code is not None:
        return _team_id_by_code
    mapping: dict[str, str] = {}
    try:
        payload = _get_json(f"{ESPN_NBA_TEAMS}?limit=50")
        teams = (payload.get("sports") or [{}])[0].get("leagues") or [{}]
        for league in teams:
            for wrap in league.get("teams") or []:
                team = wrap.get("team") or {}
                ab = normalize_nba_team(str(team.get("abbreviation") or ""))
                tid = str(team.get("id") or "")
                if ab and tid and is_nba_franchise(ab):
                    mapping[ab] = tid
    except Exception as exc:  # noqa: BLE001
        logger.warning("ESPN NBA team index failed: %s", exc)
    _team_id_by_code = mapping
    return mapping


def roster_name_set(
    team_code: str,
    *,
    season: int = ESPN_NBA_SEASON_END_YEAR,
) -> set[str]:
    """Normalized display names on ESPN roster for a franchise."""
    code = normalize_nba_team(team_code)
    cache_key = (code, season)
    if cache_key in _roster_cache:
        return _roster_cache[cache_key]
    names: set[str] = set()
    tid = _load_team_ids().get(code)
    if not tid:
        _roster_cache[cache_key] = names
        return names
    try:
        payload = _get_json(f"{ESPN_NBA_ROSTER.format(team_id=tid)}?season={season}")
        for ath in payload.get("athletes") or []:
            if not isinstance(ath, dict):
                continue
            nm = ath.get("displayName") or ath.get("fullName") or ""
            if nm:
                names.add(_norm_name(str(nm)))
    except Exception as exc:  # noqa: BLE001
        logger.debug("ESPN roster fetch failed for %s: %s", code, exc)
    _roster_cache[cache_key] = names
    return names


def roster_player_entries(*, season: int = ESPN_NBA_SEASON_END_YEAR) -> dict[str, dict[str, str]]:
    """Normalized name -> {team, display_name}."""
    if season in _player_team_map_cache:
        return _player_team_map_cache[season]
    mapping: dict[str, dict[str, str]] = {}
    for code, tid in _load_team_ids().items():
        try:
            payload = _get_json(f"{ESPN_NBA_ROSTER.format(team_id=tid)}?season={season}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("ESPN roster map fetch failed for %s: %s", code, exc)
            continue
        for ath in payload.get("athletes") or []:
            if not isinstance(ath, dict):
                continue
            display = str(ath.get("displayName") or ath.get("fullName") or "").strip()
            if display:
                mapping[_norm_name(display)] = {"team": code, "display_name": display}
    _player_team_map_cache[season] = mapping
    return mapping


def player_team_map(*, season: int = ESPN_NBA_SEASON_END_YEAR) -> dict[str, str]:
    """Normalized player name -> franchise code from live ESPN rosters (source of truth for team)."""
    return {k: v["team"] for k, v in roster_player_entries(season=season).items()}


def player_team_from_roster(
    player_name: str,
    *,
    season: int = ESPN_NBA_SEASON_END_YEAR,
) -> str | None:
    return player_team_map(season=season).get(_norm_name(player_name))


def resolve_player_team_for_game(
    player_name: str,
    *,
    home: str,
    away: str,
    reported_team: str | None = None,
    season: int = ESPN_NBA_SEASON_END_YEAR,
) -> str | None:
    """Roster assignment wins over injury-feed or rate-file team hints."""
    home = normalize_nba_team(home)
    away = normalize_nba_team(away)
    game = {home, away}
    roster_team = player_team_from_roster(player_name, season=season)
    if roster_team and roster_team in game:
        return roster_team
    if roster_team and roster_team not in game:
        return None
    pk = _norm_name(player_name)
    on_home = pk in roster_name_set(home, season=season)
    on_away = pk in roster_name_set(away, season=season)
    if on_home and not on_away:
        return home
    if on_away and not on_home:
        return away
    if reported_team:
        rt = normalize_nba_team(reported_team)
        if rt in game:
            return rt
    return None


def clear_roster_cache() -> None:
    global _team_id_by_code
    _team_id_by_code = None
    _roster_cache.clear()
    _player_team_map_cache.clear()


def player_team_for_event(
    player_name: str,
    *,
    home: str,
    away: str,
    rate_team: str | None = None,
) -> str | None:
    """Return franchise code if player is eligible for this game, else None."""
    home = normalize_nba_team(home)
    away = normalize_nba_team(away)
    game = {home, away}
    if rate_team:
        rt = normalize_nba_team(rate_team)
        return rt if rt in game else None
    pk = _norm_name(player_name)
    on_home = pk in roster_name_set(home)
    on_away = pk in roster_name_set(away)
    if on_home and not on_away:
        return home
    if on_away and not on_home:
        return away
    return None
