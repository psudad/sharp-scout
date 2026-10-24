"""Offline fixtures for NBA shadow pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sharp_scout.nba.projections import default_demo_rates


def mock_nba_events() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    return [
        {
            "event_id": "demo-nba-cha-mia",
            "sport_key": "basketball_nba",
            "sport": "nba",
            "commence_time": now,
            "home_team": "MIA",
            "away_team": "CHA",
            "home_team_raw": "Miami Heat",
            "away_team_raw": "Charlotte Hornets",
            "captured_at": now,
            "bookmakers": {
                "pinnacle": {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "is_sharp": True,
                    "markets": {
                        "spreads": [
                            {"side": "away", "name": "Charlotte Hornets", "price": -110, "point": 4.5},
                            {"side": "home", "name": "Miami Heat", "price": -110, "point": -4.5},
                        ],
                        "totals": [
                            {"side": "over", "name": "Over", "price": -110, "point": 224.5},
                            {"side": "under", "name": "Under", "price": -110, "point": 224.5},
                        ],
                        "h2h": [
                            {"side": "away", "name": "Charlotte Hornets", "price": 165, "point": None},
                            {"side": "home", "name": "Miami Heat", "price": -190, "point": None},
                        ],
                    },
                },
                "draftkings": {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "is_sharp": False,
                    "markets": {
                        "spreads": [
                            {"side": "away", "name": "Charlotte Hornets", "price": -105, "point": 5.5},
                            {"side": "home", "name": "Miami Heat", "price": -115, "point": -5.5},
                        ],
                        "totals": [
                            {"side": "over", "name": "Over", "price": -105, "point": 223.5},
                            {"side": "under", "name": "Under", "price": -115, "point": 223.5},
                        ],
                    },
                },
                "fanduel": {
                    "key": "fanduel",
                    "title": "FanDuel",
                    "is_sharp": False,
                    "markets": {
                        "spreads": [
                            {"side": "away", "name": "Charlotte Hornets", "price": 100, "point": 5.5},
                            {"side": "home", "name": "Miami Heat", "price": -120, "point": -5.5},
                        ],
                        "player_points": [
                            {
                                "side": "over",
                                "name": "Over",
                                "description": "LaMelo Ball",
                                "price": -105,
                                "point": 20.5,
                            },
                            {
                                "side": "under",
                                "name": "Under",
                                "description": "LaMelo Ball",
                                "price": -115,
                                "point": 20.5,
                            },
                            {
                                "side": "over",
                                "name": "Over",
                                "description": "Jimmy Butler",
                                "price": -110,
                                "point": 19.5,
                            },
                            {
                                "side": "under",
                                "name": "Under",
                                "description": "Jimmy Butler",
                                "price": -110,
                                "point": 19.5,
                            },
                        ],
                        "player_rebounds": [
                            {
                                "side": "over",
                                "name": "Over",
                                "description": "LaMelo Ball",
                                "price": -120,
                                "point": 5.5,
                            },
                            {
                                "side": "under",
                                "name": "Under",
                                "description": "LaMelo Ball",
                                "price": 100,
                                "point": 5.5,
                            },
                        ],
                    },
                },
                "betmgm": {
                    "key": "betmgm",
                    "title": "BetMGM",
                    "is_sharp": False,
                    "markets": {
                        "player_points": [
                            {
                                "side": "over",
                                "name": "Over",
                                "description": "LaMelo Ball",
                                "price": -110,
                                "point": 21.5,
                            },
                            {
                                "side": "under",
                                "name": "Under",
                                "description": "LaMelo Ball",
                                "price": -110,
                                "point": 21.5,
                            },
                        ],
                    },
                },
                "williamhill_us": {
                    "key": "williamhill_us",
                    "title": "Caesars",
                    "is_sharp": False,
                    "markets": {
                        "player_points": [
                            {
                                "side": "over",
                                "name": "Over",
                                "description": "LaMelo Ball",
                                "price": -112,
                                "point": 21.5,
                            },
                            {
                                "side": "under",
                                "name": "Under",
                                "description": "LaMelo Ball",
                                "price": -108,
                                "point": 21.5,
                            },
                        ],
                    },
                },
            },
        }
    ]


def demo_player_rates():
    return default_demo_rates()
