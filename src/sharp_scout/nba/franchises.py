"""The 30 NBA franchises (excludes exhibition / All-Star / international opponents)."""

from __future__ import annotations

NBA_FRANCHISES = frozenset(
    {
        "ATL",
        "BOS",
        "BKN",
        "CHA",
        "CHI",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GSW",
        "HOU",
        "IND",
        "LAC",
        "LAL",
        "MEM",
        "MIA",
        "MIL",
        "MIN",
        "NOP",
        "NYK",
        "OKC",
        "ORL",
        "PHI",
        "PHX",
        "POR",
        "SAC",
        "SAS",
        "TOR",
        "UTA",
        "WAS",
    }
)


def is_nba_franchise(code: str) -> bool:
    return (code or "").upper() in NBA_FRANCHISES


def is_nba_regular_matchup(home: str, away: str) -> bool:
    return is_nba_franchise(home) and is_nba_franchise(away)
