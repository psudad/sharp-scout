"""Simple NBA prop projections: minutes × per-minute rates with usage redistribution."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sharp_scout.nba import paths as nba_paths

logger = logging.getLogger(__name__)

STAT_FIELDS = {
    "player_points": "pts_per_min",
    "player_rebounds": "reb_per_min",
    "player_assists": "ast_per_min",
    "player_threes": "fg3_per_min",
}


@dataclass
class PlayerRateRow:
    player_name: str
    team: str
    minutes: float
    pts_per_min: float = 0.0
    reb_per_min: float = 0.0
    ast_per_min: float = 0.0
    fg3_per_min: float = 0.0
    usage_share: float = 0.18
    out_teammates: list[str] = field(default_factory=list)


def load_rate_table(path: Path | None = None) -> dict[str, PlayerRateRow]:
    p = path or nba_paths.NBA_PLAYER_RATES_PATH
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    rows = raw.get("players") if isinstance(raw, dict) else raw
    out: dict[str, PlayerRateRow] = {}
    for row in rows or []:
        name = str(row.get("player_name") or row.get("name") or "")
        if not name:
            continue
        out[_norm(name)] = PlayerRateRow(
            player_name=name,
            team=str(row.get("team") or ""),
            minutes=float(row.get("minutes") or 28.0),
            pts_per_min=float(row.get("pts_per_min") or 0.0),
            reb_per_min=float(row.get("reb_per_min") or 0.0),
            ast_per_min=float(row.get("ast_per_min") or 0.0),
            fg3_per_min=float(row.get("fg3_per_min") or 0.0),
            usage_share=float(row.get("usage_share") or 0.18),
            out_teammates=list(row.get("out_teammates") or []),
        )
    return out


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


def _usage_multiplier(row: PlayerRateRow, table: dict[str, PlayerRateRow]) -> float:
    if not row.out_teammates:
        return 1.0
    boost = 0.0
    for mate in row.out_teammates:
        other = table.get(_norm(mate))
        if other and other.team == row.team:
            boost += other.usage_share * 0.35
    return 1.0 + min(boost, 0.25)


def projected_minutes(row: PlayerRateRow, table: dict[str, PlayerRateRow]) -> float:
    return row.minutes * _usage_multiplier(row, table)


def project_mean(row: PlayerRateRow, market: str, table: dict[str, PlayerRateRow]) -> float | None:
    mins = projected_minutes(row, table)
    if market == "player_points_rebounds_assists":
        if not row.pts_per_min and not row.reb_per_min and not row.ast_per_min:
            return None
        return mins * (row.pts_per_min + row.reb_per_min + row.ast_per_min)
    field_name = STAT_FIELDS.get(market)
    if not field_name:
        return None
    rate = getattr(row, field_name, 0.0)
    return mins * rate


def default_demo_rates() -> dict[str, PlayerRateRow]:
    """Deterministic rates for offline demo (MIA @ CHA fixture)."""
    return {
        "lamelo ball": PlayerRateRow(
            player_name="LaMelo Ball",
            team="CHA",
            minutes=32.0,
            pts_per_min=0.72,
            reb_per_min=0.18,
            ast_per_min=0.22,
            fg3_per_min=0.11,
            usage_share=0.28,
        ),
        "jimmy butler": PlayerRateRow(
            player_name="Jimmy Butler",
            team="MIA",
            minutes=33.0,
            pts_per_min=0.58,
            reb_per_min=0.17,
            ast_per_min=0.15,
            fg3_per_min=0.04,
            usage_share=0.26,
            out_teammates=[],
        ),
    }
