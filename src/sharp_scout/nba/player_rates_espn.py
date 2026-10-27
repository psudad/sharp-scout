"""Build nba_player_rates.json from ESPN (roster = team, by-athlete = stats)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sharp_scout.data.espn_cfb import _get_json
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.rosters import ESPN_NBA_SEASON_END_YEAR, roster_norm_name, roster_player_entries

logger = logging.getLogger(__name__)

BY_ATHLETE = (
    "https://site.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete"
)


def _category_values(
    athlete_wrap: dict[str, Any],
    cat_name: str,
    *,
    schema: dict[str, dict[str, Any]],
) -> dict[str, float]:
    out: dict[str, float] = {}
    schema_cat = schema.get(cat_name) or {}
    names = schema_cat.get("names") or []
    labels = schema_cat.get("labels") or names
    for cat in athlete_wrap.get("categories") or []:
        if str(cat.get("name") or "") != cat_name:
            continue
        values = cat.get("values")
        if not values:
            totals = cat.get("totals") or []
            try:
                values = [float(x) for x in totals]
            except (TypeError, ValueError):
                values = []
        for i, nm in enumerate(names):
            if i < len(values):
                try:
                    out[str(nm)] = float(values[i])
                except (TypeError, ValueError):
                    pass
        for i, lb in enumerate(labels):
            if i < len(values) and lb:
                try:
                    out[str(lb).upper()] = float(values[i])
                except (TypeError, ValueError):
                    pass
    return out


def _stat_row_from_athlete(
    athlete_wrap: dict[str, Any],
    *,
    schema: dict[str, dict[str, Any]],
) -> dict[str, float]:
    general = _category_values(athlete_wrap, "general", schema=schema)
    offensive = _category_values(athlete_wrap, "offensive", schema=schema)
    mpg = general.get("avgMinutes") or general.get("AVGMINUTES")
    if mpg is None:
        gp = general.get("gamesPlayed") or general.get("GP") or 0
        mins = general.get("minutes") or general.get("MIN") or 0
        mpg = float(mins) / float(gp) if gp else 0.0
    pts = offensive.get("avgPoints") or offensive.get("PTS")
    ast = offensive.get("avgAssists") or offensive.get("AST")
    reb = general.get("avgRebounds") or general.get("REB")
    fg3 = offensive.get("avgThreePointFieldGoalsMade") or offensive.get("3PM")
    fga = offensive.get("avgFieldGoalsAttempted") or offensive.get("FGA")
    fta = offensive.get("avgFreeThrowsAttempted") or offensive.get("FTA")
    mpg_f = float(mpg or 0)
    if mpg_f <= 0:
        return {}
    pts_f = float(pts or 0)
    return {
        "minutes": mpg_f,
        "pts_per_min": pts_f / mpg_f,
        "reb_per_min": float(reb or 0) / mpg_f,
        "ast_per_min": float(ast or 0) / mpg_f,
        "fg3_per_min": float(fg3 or 0) / mpg_f,
        "usage_share": min(
            0.38,
            max(0.08, (float(fga or 0) + 0.44 * float(fta or 0) + float(ast or 0)) / max(mpg_f * 2.2, 1)),
        ),
    }


def _schema_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    schema: dict[str, dict[str, Any]] = {}
    for cat in payload.get("categories") or []:
        nm = str(cat.get("name") or "")
        if nm:
            schema[nm] = cat
    return schema


def _fetch_stats_by_name(*, season: int) -> dict[str, dict[str, float]]:
    """Player display name (normalized) -> rate fields. Team is intentionally omitted."""
    out: dict[str, dict[str, float]] = {}
    page = 1
    schema: dict[str, dict[str, Any]] = {}
    while True:
        url = f"{BY_ATHLETE}?limit=50&page={page}&sort=offensive:points:desc&season={season}"
        try:
            payload = _get_json(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESPN by-athlete page %s failed: %s", page, exc)
            break
        if not schema:
            schema = _schema_from_payload(payload)
        athletes = payload.get("athletes") or []
        if not athletes:
            break
        for wrap in athletes:
            athlete = wrap.get("athlete") or {}
            name = str(athlete.get("displayName") or athlete.get("fullName") or "").strip()
            if not name:
                continue
            stats = _stat_row_from_athlete(wrap, schema=schema)
            if stats:
                out[roster_norm_name(name)] = stats
        pagination = payload.get("pagination") or {}
        if page >= int(pagination.get("pages") or page):
            break
        page += 1
    logger.info("ESPN by-athlete season=%s: %d players with stats", season, len(out))
    return out


def build_player_rate_rows(*, season: int = ESPN_NBA_SEASON_END_YEAR) -> list[dict[str, Any]]:
    """Team codes from live ESPN rosters; stat values from current season, prior season fallback."""
    roster = roster_player_entries(season=season)
    current = _fetch_stats_by_name(season=season)
    prior = _fetch_stats_by_name(season=season - 1) if season else {}
    rows: list[dict[str, Any]] = []
    for norm_name, entry in sorted(roster.items()):
        team = entry["team"]
        stats = current.get(norm_name) or prior.get(norm_name)
        if not stats:
            continue
        rows.append(
            {
                "player_name": entry["display_name"],
                "team": team,
                "minutes": stats["minutes"],
                "pts_per_min": round(stats["pts_per_min"], 4),
                "reb_per_min": round(stats["reb_per_min"], 4),
                "ast_per_min": round(stats["ast_per_min"], 4),
                "fg3_per_min": round(stats.get("fg3_per_min") or 0, 4),
                "usage_share": round(stats["usage_share"], 4),
                "stats_season": season if norm_name in current else season - 1,
                "out_teammates": [],
            }
        )
    return rows


def refresh_nba_player_rates_file(
    path: Any = None,
    *,
    season: int = ESPN_NBA_SEASON_END_YEAR,
) -> int:
    p = path or nba_paths.NBA_PLAYER_RATES_PATH
    rows = build_player_rate_rows(season=season)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "season_end_year": season,
        "source": "espn_roster_and_byathlete",
        "players": rows,
    }
    p.write_text(json.dumps(payload, indent=2) + "\n")
    logger.info("Wrote %d player rate rows to %s", len(rows), p)
    return len(rows)
