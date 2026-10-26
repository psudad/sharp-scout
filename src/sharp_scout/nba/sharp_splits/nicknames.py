"""Map Action Network nicknames (and codes) to NBA franchise codes."""

from __future__ import annotations

from sharp_scout.nba.teams import normalize_nba_team

# Common Action Network / media nicknames (case-insensitive keys).
NICKNAME_TO_CODE: dict[str, str] = {
    "HAWKS": "ATL",
    "CELTICS": "BOS",
    "NETS": "BKN",
    "HORNETS": "CHA",
    "BULLS": "CHI",
    "CAVALIERS": "CLE",
    "CAVS": "CLE",
    "MAVERICKS": "DAL",
    "MAVS": "DAL",
    "NUGGETS": "DEN",
    "PISTONS": "DET",
    "WARRIORS": "GSW",
    "ROCKETS": "HOU",
    "PACERS": "IND",
    "CLIPPERS": "LAC",
    "LAKERS": "LAL",
    "GRIZZLIES": "MEM",
    "HEAT": "MIA",
    "BUCKS": "MIL",
    "TIMBERWOLVES": "MIN",
    "WOLVES": "MIN",
    "PELICANS": "NOP",
    "KNICKS": "NYK",
    "THUNDER": "OKC",
    "MAGIC": "ORL",
    "76ERS": "PHI",
    "SIXERS": "PHI",
    "SUNS": "PHX",
    "TRAIL BLAZERS": "POR",
    "BLAZERS": "POR",
    "KINGS": "SAC",
    "SPURS": "SAS",
    "RAPTORS": "TOR",
    "JAZZ": "UTA",
    "WIZARDS": "WAS",
}


def team_code_from_snapshot_label(label: str) -> str:
    key = (label or "").strip().upper()
    if key in NICKNAME_TO_CODE:
        return NICKNAME_TO_CODE[key]
    return normalize_nba_team(label)
