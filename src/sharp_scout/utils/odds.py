"""Shared helpers: American odds, team IDs, logging."""

from __future__ import annotations

import logging
import math
from typing import Iterable

TEAM_ALIASES: dict[str, str] = {
    "ARI": "ARI",
    "ARIZONA": "ARI",
    "ARIZONA CARDINALS": "ARI",
    "ATL": "ATL",
    "ATLANTA": "ATL",
    "ATLANTA FALCONS": "ATL",
    "BAL": "BAL",
    "BALTIMORE": "BAL",
    "BALTIMORE RAVENS": "BAL",
    "BUF": "BUF",
    "BUFFALO": "BUF",
    "BUFFALO BILLS": "BUF",
    "CAR": "CAR",
    "CAROLINA": "CAR",
    "CAROLINA PANTHERS": "CAR",
    "CHI": "CHI",
    "CHICAGO": "CHI",
    "CHICAGO BEARS": "CHI",
    "CIN": "CIN",
    "CINCINNATI": "CIN",
    "CINCINNATI BENGALS": "CIN",
    "CLE": "CLE",
    "CLEVELAND": "CLE",
    "CLEVELAND BROWNS": "CLE",
    "DAL": "DAL",
    "DALLAS": "DAL",
    "DALLAS COWBOYS": "DAL",
    "DEN": "DEN",
    "DENVER": "DEN",
    "DENVER BRONCOS": "DEN",
    "DET": "DET",
    "DETROIT": "DET",
    "DETROIT LIONS": "DET",
    "GB": "GB",
    "GNB": "GB",
    "GREEN BAY": "GB",
    "GREEN BAY PACKERS": "GB",
    "HOU": "HOU",
    "HOUSTON": "HOU",
    "HOUSTON TEXANS": "HOU",
    "IND": "IND",
    "INDIANAPOLIS": "IND",
    "INDIANAPOLIS COLTS": "IND",
    "JAX": "JAX",
    "JAC": "JAX",
    "JACKSONVILLE": "JAX",
    "JACKSONVILLE JAGUARS": "JAX",
    "KC": "KC",
    "KAN": "KC",
    "KANSAS CITY": "KC",
    "KANSAS CITY CHIEFS": "KC",
    "LA": "LAR",
    "LAR": "LAR",
    "LOS ANGELES RAMS": "LAR",
    "LA RAMS": "LAR",
    "LAC": "LAC",
    "LOS ANGELES CHARGERS": "LAC",
    "LA CHARGERS": "LAC",
    "LV": "LV",
    "LVR": "LV",
    "OAK": "LV",
    "LAS VEGAS": "LV",
    "LAS VEGAS RAIDERS": "LV",
    "MIA": "MIA",
    "MIAMI": "MIA",
    "MIAMI DOLPHINS": "MIA",
    "MIN": "MIN",
    "MINNESOTA": "MIN",
    "MINNESOTA VIKINGS": "MIN",
    "NE": "NE",
    "NWE": "NE",
    "NEW ENGLAND": "NE",
    "NEW ENGLAND PATRIOTS": "NE",
    "NO": "NO",
    "NOR": "NO",
    "NEW ORLEANS": "NO",
    "NEW ORLEANS SAINTS": "NO",
    "NYG": "NYG",
    "NEW YORK GIANTS": "NYG",
    "NYJ": "NYJ",
    "NEW YORK JETS": "NYJ",
    "PHI": "PHI",
    "PHILADELPHIA": "PHI",
    "PHILADELPHIA EAGLES": "PHI",
    "PIT": "PIT",
    "PITTSBURGH": "PIT",
    "PITTSBURGH STEELERS": "PIT",
    "SEA": "SEA",
    "SEATTLE": "SEA",
    "SEATTLE SEAHAWKS": "SEA",
    "SF": "SF",
    "SFO": "SF",
    "SAN FRANCISCO": "SF",
    "SAN FRANCISCO 49ERS": "SF",
    "TB": "TB",
    "TAM": "TB",
    "TAMPA BAY": "TB",
    "TAMPA BAY BUCCANEERS": "TB",
    "TEN": "TEN",
    "TENNESSEE": "TEN",
    "TENNESSEE TITANS": "TEN",
    "WAS": "WAS",
    "WSH": "WAS",
    "WASHINGTON": "WAS",
    "WASHINGTON COMMANDERS": "WAS",
    "WASHINGTON FOOTBALL TEAM": "WAS",
}


def normalize_team(name: str, sport: str = "nfl") -> str:
    if (sport or "nfl").lower() == "ncaaf":
        from sharp_scout.utils.teams import normalize_ncaaf

        return normalize_ncaaf(name)
    key = name.strip().upper()
    if key in TEAM_ALIASES:
        return TEAM_ALIASES[key]
    # Odds API sometimes returns "Los Angeles Rams"
    return TEAM_ALIASES.get(key, key[:3])


def american_to_implied_prob(american: float) -> float:
    if american == 0:
        raise ValueError("American odds cannot be 0")
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def implied_prob_to_american(p: float) -> int:
    p = min(max(p, 1e-6), 1 - 1e-6)
    if p >= 0.5:
        return int(round(-100 * p / (1 - p)))
    return int(round(100 * (1 - p) / p))


def decimal_to_american(decimal_odds: float) -> int:
    if decimal_odds <= 1.0:
        raise ValueError("Decimal odds must be > 1")
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    return int(round(-100 / (decimal_odds - 1)))


def expected_value(p_true: float, american_odds: float) -> float:
    """EV as fraction of stake: p * decimal - 1."""
    if american_odds > 0:
        decimal = 1 + american_odds / 100.0
    else:
        decimal = 1 + 100.0 / abs(american_odds)
    return p_true * decimal - 1.0


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def mean_or_none(xs: Iterable[float]) -> float | None:
    vals = list(xs)
    if not vals:
        return None
    return sum(vals) / len(vals)