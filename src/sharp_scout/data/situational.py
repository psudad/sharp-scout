"""Stadium coordinates + simple situational adjustments."""

from __future__ import annotations

# Approximate stadium lat/lon for travel distance
STADIUMS: dict[str, tuple[float, float]] = {
    "ARI": (33.5275, -112.2625),
    "ATL": (33.7554, -84.4010),
    "BAL": (39.2780, -76.6227),
    "BUF": (42.7738, -78.7870),
    "CAR": (35.2258, -80.8528),
    "CHI": (41.8623, -87.6167),
    "CIN": (39.0950, -84.5160),
    "CLE": (41.5061, -81.6995),
    "DAL": (32.7473, -97.0945),
    "DEN": (39.7439, -105.0201),
    "DET": (42.3400, -83.0456),
    "GB": (44.5013, -88.0622),
    "HOU": (29.6847, -95.4107),
    "IND": (39.7601, -86.1639),
    "JAX": (30.3239, -81.6373),
    "KC": (39.0489, -94.4839),
    "LAC": (33.9535, -118.3392),
    "LAR": (33.9535, -118.3392),
    "LV": (36.0908, -115.1830),
    "MIA": (25.9580, -80.2389),
    "MIN": (44.9738, -93.2575),
    "NE": (42.0909, -71.2643),
    "NO": (29.9511, -90.0812),
    "NYG": (40.8128, -74.0742),
    "NYJ": (40.8128, -74.0742),
    "PHI": (39.9008, -75.1675),
    "PIT": (40.4468, -80.0158),
    "SEA": (47.5952, -122.3316),
    "SF": (37.4030, -121.9700),
    "TB": (27.9759, -82.5033),
    "TEN": (36.1665, -86.7713),
    "WAS": (38.9077, -76.8645),
}

# Baseline HFA in points (league average ~2.0–2.5); refined per-team later
BASE_HFA = 2.2


# Major FBS venues (lat, lon) — used for NCAAF travel adjustment
NCAAF_STADIUMS: dict[str, tuple[float, float]] = {
    "ALA": (33.208, -87.550),
    "UGA": (33.950, -83.373),
    "OSU": (40.002, -83.019),
    "MICH": (42.266, -83.749),
    "TEX": (30.284, -97.733),
    "OU": (35.206, -97.442),
    "ORE": (44.058, -123.069),
    "PSU": (40.812, -77.856),
    "CLEM": (34.679, -82.843),
    "ND": (41.698, -86.234),
    "LSU": (30.412, -91.184),
    "FSU": (30.438, -84.304),
    "MIA": (25.748, -80.313),
    "USC": (34.014, -118.288),
    "UCLA": (34.161, -118.167),
    "WASH": (47.650, -122.302),
    "TENN": (35.955, -83.925),
    "TAMU": (30.610, -96.340),
    "FLA": (29.650, -82.349),
    "AUB": (32.602, -85.489),
}


def travel_miles(away: str, home: str, stadiums: dict[str, tuple[float, float]] | None = None) -> float:
    from sharp_scout.utils.odds import haversine_miles

    table = stadiums if stadiums is not None else STADIUMS
    if away not in table or home not in table:
        return 0.0
    a, b = table[away], table[home]
    return haversine_miles(a[0], a[1], b[0], b[1])


def rest_advantage(home_days_rest: int, away_days_rest: int) -> float:
    """Approximate points added to home from rest differential."""
    diff = home_days_rest - away_days_rest
    return 0.35 * diff


def weather_adjustment(wind_mph: float | None, precip: bool = False) -> dict[str, float]:
    """Return adjustments to total and pass EPA environment."""
    wind = wind_mph or 0.0
    total_adj = 0.0
    if wind >= 15:
        total_adj -= 1.5
    if wind >= 20:
        total_adj -= 2.0
    if precip:
        total_adj -= 1.0
    return {"total_adj": total_adj, "pass_penalty": min(wind / 40.0, 0.25)}


def situational_spread_adj(
    home: str,
    away: str,
    home_rest: int = 7,
    away_rest: int = 7,
    wind_mph: float | None = None,
    precip: bool = False,
    hfa: float = BASE_HFA,
    stadiums: dict[str, tuple[float, float]] | None = None,
) -> dict[str, float]:
    travel = travel_miles(away, home, stadiums=stadiums)
    travel_pts = min(travel / 2500.0, 0.8)  # long cross-country slight home boost
    rest = rest_advantage(home_rest, away_rest)
    wx = weather_adjustment(wind_mph, precip)
    # Positive = favors home (home gets points)
    spread_home_boost = hfa + travel_pts + rest
    return {
        "home_points_boost": spread_home_boost,
        "total_adj": wx["total_adj"],
        "travel_miles": travel,
        "rest_adj": rest,
        "hfa": hfa,
    }