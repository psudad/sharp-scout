"""Margin impact when a player is out (not raw scoring — replacement absorbs usage)."""

from __future__ import annotations

import json
import re
from typing import Any

from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.player_rates_espn import build_supplemental_rate_row, season_stats_by_name
from sharp_scout.nba.rosters import ESPN_NBA_SEASON_END_YEAR, roster_norm_name

REPLACEMENT_BPM = -2.0  # per-100 possessions vs replacement player
LEAGUE_PACE = 100.0
MAX_MARGIN_IMPACT = 8.0
MAX_OFF_PTS_GAME = 6.0
MAX_DEF_PTS_GAME = 4.5
MAX_PACE_PTS_GAME = 2.0
OFF_BPM_SHARE = 0.62
DEF_BPM_SHARE = 0.38
MIN_GAMES_TRUST_CURRENT = 8
ROTATION_MIN_MPG = 8.0

_SEASON_LONG_DETAIL = re.compile(
    r"(?:"
    r"for the season|rest of the season|out for the season|"
    r"expected to miss(?:\s+\w+){0,3}\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|several)\s+months|"
    r"miss(?:ing)?\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|several)\s+months|"
    r"torn\s+(?:\w+\s+){0,2}(?:acl|achilles|meniscus)"
    r")",
    re.IGNORECASE,
)

# Documented formula (paper / PR):
#   bpm_proxy = box-score on-court value (per 100 poss, heuristic from rates file)
#   margin_pts = (bpm_proxy - REPLACEMENT_BPM) × (MPG / 48) × (pace / 100)
#   off_pts / def_pts split bpm_proxy by OFF_BPM_SHARE / DEF_BPM_SHARE before scaling
#   clamp per-player game impacts to MAX_OFF_PTS_GAME / MAX_DEF_PTS_GAME / MAX_PACE_PTS_GAME


def is_season_long_absence(
    *,
    detail: str | None = None,
    current_season_gp: int | None = None,
    played_this_season: bool | None = None,
) -> bool:
    """Skip adjustment when absence is already baked into team ratings."""
    text = str(detail or "")
    if _SEASON_LONG_DETAIL.search(text):
        return True
    gp = current_season_gp
    if gp is None and played_this_season is not None:
        gp = 0 if not played_this_season else 1
    if gp is not None and gp <= 0 and re.search(
        r"(?:underwent|surgery|rehabilitation|re-evaluated in \d+)",
        text,
        re.I,
    ):
        if _SEASON_LONG_DETAIL.search(text) or re.search(
            r"(?:achilles|acl|meniscus|fracture)", text, re.I
        ):
            return True
    return False


def impact_rate_row(
    row: dict[str, Any],
    *,
    season_end: int = ESPN_NBA_SEASON_END_YEAR,
) -> dict[str, Any]:
    """Row copy with blended rates when current-season sample is small."""
    out = dict(row)
    if out.get("current_season_gp") is not None:
        gp = int(out.get("current_season_gp") or 0)
    elif out.get("games_played") is not None:
        gp = int(out.get("games_played") or 0)
    elif int(out.get("stats_season") or season_end) >= season_end:
        gp = MIN_GAMES_TRUST_CURRENT
    else:
        gp = 0
    mpg = float(out.get("minutes") or 0)
    if gp < MIN_GAMES_TRUST_CURRENT:
        prior_stats = season_stats_by_name(season=season_end - 1).get(
            roster_norm_name(str(out.get("player_name") or ""))
        )
        if prior_stats:
            w = max(0.0, min(1.0, gp / float(MIN_GAMES_TRUST_CURRENT)))
            for field in ("minutes", "pts_per_min", "reb_per_min", "ast_per_min", "usage_share"):
                cur = float(out.get(field) or 0)
                prv = float(prior_stats.get(field) or cur)
                out[field] = prv * (1.0 - w) + cur * w
    if mpg >= 24 and bpm_proxy_per100(out) < REPLACEMENT_BPM:
        out["pts_per_min"] = max(float(out.get("pts_per_min") or 0), 0.38)
        out["usage_share"] = max(float(out.get("usage_share") or 0), 0.20)
    elif mpg >= 18 and bpm_proxy_per100(out) < REPLACEMENT_BPM:
        out["pts_per_min"] = max(float(out.get("pts_per_min") or 0), 0.30)
    mpg = float(out.get("minutes") or 0)
    if mpg >= 22 and bpm_proxy_per100(out) < REPLACEMENT_BPM:
        out["pts_per_min"] = max(float(out.get("pts_per_min") or 0), 0.35)
        out["usage_share"] = max(float(out.get("usage_share") or 0), 0.18)
    return out


def rotation_bpm_proxy(row: dict[str, Any]) -> float:
    """BPM proxy with a floor so cold starts / sparse rate rows still move rotation minutes."""
    bpm = bpm_proxy_per100(row)
    mpg = float(row.get("minutes") or row.get("mpg") or 0)
    if mpg >= 24:
        floor = REPLACEMENT_BPM + 1.25
    elif mpg >= 18:
        floor = REPLACEMENT_BPM + 0.65
    elif mpg >= ROTATION_MIN_MPG:
        floor = REPLACEMENT_BPM + 0.15
    else:
        floor = REPLACEMENT_BPM
    return max(bpm, floor)


def bpm_proxy_per100(row: dict[str, Any]) -> float:
    """BPM-like per-100 from shadow player rates (pts/reb/ast per min + usage)."""
    pts48 = float(row["pts_per_min"]) * 48.0
    reb48 = float(row.get("reb_per_min") or 0) * 48.0
    ast48 = float(row.get("ast_per_min") or 0) * 48.0
    usage = float(row.get("usage_share") or 0.20)
    return pts48 * 0.45 + reb48 * 0.08 + ast48 * 0.18 + usage * 12.0 - 14.0


def _scale_bpm_to_game_pts(bpm: float, row: dict[str, Any], *, pace: float = LEAGUE_PACE) -> float:
    mpg = float(row.get("minutes") or row.get("mpg") or 0)
    if mpg <= 0 or bpm <= REPLACEMENT_BPM:
        return 0.0
    return max((bpm - REPLACEMENT_BPM) * (mpg / 48.0) * (pace / LEAGUE_PACE), 0.0)


def margin_impact_pts(row: dict[str, Any], *, pace: float = LEAGUE_PACE) -> float:
    bpm = rotation_bpm_proxy(row)
    return min(_scale_bpm_to_game_pts(bpm, row, pace=pace), MAX_MARGIN_IMPACT)


def offense_impact_pts(row: dict[str, Any], *, pace: float = LEAGUE_PACE) -> float:
    bpm = rotation_bpm_proxy(row) * OFF_BPM_SHARE
    return min(_scale_bpm_to_game_pts(bpm, row, pace=pace), MAX_OFF_PTS_GAME)


def defense_impact_pts(row: dict[str, Any], *, pace: float = LEAGUE_PACE) -> float:
    bpm = rotation_bpm_proxy(row) * DEF_BPM_SHARE
    return min(_scale_bpm_to_game_pts(bpm, row, pace=pace), MAX_DEF_PTS_GAME)


def pace_impact_pts(row: dict[str, Any], *, pace: float = LEAGUE_PACE) -> float:
    """Possessions lost when a high-minute creator/scorer sits."""
    mpg = float(row.get("minutes") or row.get("mpg") or 0)
    if mpg < 20:
        return 0.0
    usage = float(row.get("usage_share") or 0.18)
    raw = (mpg / 48.0) * usage * (pace / LEAGUE_PACE) * 3.5
    return min(raw, MAX_PACE_PTS_GAME)


def load_rates_by_team_player() -> dict[str, dict[str, Any]]:
    """Key: 'TEAM|player name lower' -> rate row."""
    path = nba_paths.NBA_PLAYER_RATES_PATH
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    rows = raw.get("players") if isinstance(raw.get("players"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("player_name") or row.get("name")
        team = row.get("team")
        if not name or not team:
            continue
        key = f"{str(team).upper()}|{str(name).strip().lower()}"
        out[key] = row
    return out


def lookup_player_row(name: str, team: str, table: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = f"{team.upper()}|{name.strip().lower()}"
    hit = table.get(key)
    if hit is not None:
        return hit
    from sharp_scout.nba.rosters import player_team_from_roster

    roster_team = player_team_from_roster(name)
    if roster_team:
        return table.get(f"{roster_team.upper()}|{name.strip().lower()}")
    matches = [row for k, row in table.items() if k.endswith(f"|{name.strip().lower()}")]
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_player_rate_row(
    name: str,
    team: str,
    table: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Rates file, then ESPN by-athlete / minutes fallback for rotation injuries."""
    hit = lookup_player_row(name, team, table)
    if hit is None:
        hit = build_supplemental_rate_row(name, team)
    return impact_rate_row(hit)


def example_impacts(limit: int = 10) -> list[dict[str, Any]]:
    """Sample impacts for docs (from rates file + a few synthetic role players)."""
    table = load_rates_by_team_player()
    samples: list[dict[str, Any]] = []
    for key, row in sorted(table.items()):
        team, _ = key.split("|", 1)
        samples.append(
            {
                "player": row.get("player_name"),
                "team": team,
                "bpm_proxy": round(bpm_proxy_per100(row), 2),
                "margin_impact_pts": round(margin_impact_pts(row), 2),
            }
        )
    synthetics = [
        {"player_name": "Star Alpha", "team": "LAL", "minutes": 36, "pts_per_min": 0.65, "reb_per_min": 0.12, "ast_per_min": 0.20, "usage_share": 0.32},
        {"player_name": "Star Beta", "team": "DAL", "minutes": 35, "pts_per_min": 0.62, "reb_per_min": 0.11, "ast_per_min": 0.18, "usage_share": 0.30},
        {"player_name": "Starter Gamma", "team": "BOS", "minutes": 32, "pts_per_min": 0.48, "reb_per_min": 0.10, "ast_per_min": 0.12, "usage_share": 0.24},
        {"player_name": "Starter Delta", "team": "DEN", "minutes": 31, "pts_per_min": 0.44, "reb_per_min": 0.09, "ast_per_min": 0.14, "usage_share": 0.22},
        {"player_name": "Rotation Epsilon", "team": "MIA", "minutes": 24, "pts_per_min": 0.28, "reb_per_min": 0.08, "ast_per_min": 0.05, "usage_share": 0.14},
        {"player_name": "Rotation Zeta", "team": "PHX", "minutes": 22, "pts_per_min": 0.25, "reb_per_min": 0.07, "ast_per_min": 0.06, "usage_share": 0.13},
        {"player_name": "Bench Eta", "team": "NYK", "minutes": 14, "pts_per_min": 0.18, "reb_per_min": 0.06, "ast_per_min": 0.03, "usage_share": 0.10},
        {"player_name": "Bench Theta", "team": "ATL", "minutes": 12, "pts_per_min": 0.15, "reb_per_min": 0.05, "ast_per_min": 0.02, "usage_share": 0.09},
    ]
    for row in synthetics:
        samples.append(
            {
                "player": row["player_name"],
                "team": row["team"],
                "bpm_proxy": round(bpm_proxy_per100(row), 2),
                "margin_impact_pts": round(margin_impact_pts(row), 2),
            }
        )
    return samples[:limit]
