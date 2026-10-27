"""Margin impact when a player is out (not raw scoring — replacement absorbs usage)."""

from __future__ import annotations

import json
from typing import Any

from sharp_scout.nba import paths as nba_paths

REPLACEMENT_BPM = -2.0  # per-100 possessions vs replacement player
LEAGUE_PACE = 100.0
MAX_MARGIN_IMPACT = 8.0
MAX_OFF_PTS_GAME = 6.0
MAX_DEF_PTS_GAME = 4.5
MAX_PACE_PTS_GAME = 2.0
OFF_BPM_SHARE = 0.62
DEF_BPM_SHARE = 0.38

# Documented formula (paper / PR):
#   bpm_proxy = box-score on-court value (per 100 poss, heuristic from rates file)
#   margin_pts = (bpm_proxy - REPLACEMENT_BPM) × (MPG / 48) × (pace / 100)
#   off_pts / def_pts split bpm_proxy by OFF_BPM_SHARE / DEF_BPM_SHARE before scaling
#   clamp per-player game impacts to MAX_OFF_PTS_GAME / MAX_DEF_PTS_GAME / MAX_PACE_PTS_GAME


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
    bpm = bpm_proxy_per100(row)
    return min(_scale_bpm_to_game_pts(bpm, row, pace=pace), MAX_MARGIN_IMPACT)


def offense_impact_pts(row: dict[str, Any], *, pace: float = LEAGUE_PACE) -> float:
    bpm = bpm_proxy_per100(row) * OFF_BPM_SHARE
    return min(_scale_bpm_to_game_pts(bpm, row, pace=pace), MAX_OFF_PTS_GAME)


def defense_impact_pts(row: dict[str, Any], *, pace: float = LEAGUE_PACE) -> float:
    bpm = bpm_proxy_per100(row) * DEF_BPM_SHARE
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
