"""The Odds API client — Pinnacle (eu) + US retail books."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from sharp_scout.config import get_settings
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"


class OddsAPIError(RuntimeError):
    pass


class OddsClient:
    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.odds_api_key
        self.sharp_books = set(settings.sharp_books)
        self.retail_books = set(settings.retail_books)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            raise OddsAPIError(
                "ODDS_API_KEY is not set. Get a key at https://the-odds-api.com and add it to .env"
            )
        q = {"apiKey": self.api_key, **(params or {})}
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{BASE_URL}{path}", params=q)
            remaining = resp.headers.get("x-requests-remaining")
            used = resp.headers.get("x-requests-used")
            if remaining is not None:
                logger.info("Odds API quota used=%s remaining=%s", used, remaining)
            if resp.status_code == 401:
                raise OddsAPIError("Odds API unauthorized — check ODDS_API_KEY")
            if resp.status_code >= 400:
                raise OddsAPIError(f"Odds API {resp.status_code}: {resp.text[:300]}")
            return resp.json()

    def fetch_odds(
        self,
        markets: str = "h2h,spreads,totals",
        regions: str = "us,us2,eu",
        odds_format: str = "american",
    ) -> list[dict[str, Any]]:
        raw = self._get(
            f"/sports/{SPORT}/odds",
            {
                "regions": regions,
                "markets": markets,
                "oddsFormat": odds_format,
                "dateFormat": "iso",
            },
        )
        return [self._normalize_event(ev) for ev in raw]

    def _normalize_event(self, ev: dict[str, Any]) -> dict[str, Any]:
        home = normalize_team(ev.get("home_team", ""))
        away = normalize_team(ev.get("away_team", ""))
        commence = ev.get("commence_time")
        commence_dt = (
            datetime.fromisoformat(commence.replace("Z", "+00:00"))
            if isinstance(commence, str)
            else None
        )

        books: dict[str, dict[str, Any]] = {}
        for bm in ev.get("bookmakers", []) or []:
            key = (bm.get("key") or "").lower()
            title = bm.get("title") or key
            # Map Circa naming variants if aggregator exposes them
            if "circa" in key or "circa" in title.lower():
                key = "circa"
            markets: dict[str, Any] = {}
            for mkt in bm.get("markets", []) or []:
                mkey = mkt.get("key")
                outcomes = []
                for o in mkt.get("outcomes", []) or []:
                    name = o.get("name", "")
                    side = name
                    if mkey == "h2h":
                        side = "home" if normalize_team(name) == home else "away"
                        if normalize_team(name) not in (home, away):
                            side = name
                    elif mkey == "spreads":
                        team = normalize_team(name)
                        side = "home" if team == home else "away"
                    elif mkey == "totals":
                        side = name.lower()  # over / under
                    outcomes.append(
                        {
                            "side": side,
                            "name": name,
                            "price": o.get("price"),
                            "point": o.get("point"),
                        }
                    )
                markets[mkey] = outcomes
            books[key] = {
                "key": key,
                "title": title,
                "last_update": bm.get("last_update"),
                "markets": markets,
                "is_sharp": key in self.sharp_books or key == "circa",
            }

        return {
            "event_id": ev.get("id"),
            "sport_key": ev.get("sport_key"),
            "commence_time": commence_dt,
            "home_team": home,
            "away_team": away,
            "home_team_raw": ev.get("home_team"),
            "away_team_raw": ev.get("away_team"),
            "bookmakers": books,
            "captured_at": datetime.now(timezone.utc),
        }

    def pick_sharp_line(
        self, event: dict[str, Any], market: str = "spreads"
    ) -> dict[str, Any] | None:
        """Prefer Pinnacle, then Circa, then other configured sharp books."""
        preference = ["pinnacle", "circa", "circa_sports", "betfair_ex_eu"]
        books = event.get("bookmakers", {})
        for key in preference:
            if key in books and market in books[key]["markets"]:
                return {"book": key, "outcomes": books[key]["markets"][market]}
        for key, bm in books.items():
            if bm.get("is_sharp") and market in bm["markets"]:
                return {"book": key, "outcomes": bm["markets"][market]}
        return None


def mock_odds_events() -> list[dict[str, Any]]:
    """Deterministic fixture for offline / demo runs."""
    now = datetime.now(timezone.utc)
    return [
        {
            "event_id": "demo-kc-buf",
            "sport_key": SPORT,
            "commence_time": now,
            "home_team": "BUF",
            "away_team": "KC",
            "home_team_raw": "Buffalo Bills",
            "away_team_raw": "Kansas City Chiefs",
            "captured_at": now,
            "bookmakers": {
                "pinnacle": {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "is_sharp": True,
                    "markets": {
                        "spreads": [
                            {"side": "away", "name": "Kansas City Chiefs", "price": -110, "point": -2.5},
                            {"side": "home", "name": "Buffalo Bills", "price": -110, "point": 2.5},
                        ],
                        "totals": [
                            {"side": "over", "name": "Over", "price": -108, "point": 47.5},
                            {"side": "under", "name": "Under", "price": -112, "point": 47.5},
                        ],
                        "h2h": [
                            {"side": "away", "name": "Kansas City Chiefs", "price": -130, "point": None},
                            {"side": "home", "name": "Buffalo Bills", "price": 110, "point": None},
                        ],
                    },
                },
                "draftkings": {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "is_sharp": False,
                    "markets": {
                        "spreads": [
                            {"side": "away", "name": "Kansas City Chiefs", "price": -105, "point": -2.5},
                            {"side": "home", "name": "Buffalo Bills", "price": -115, "point": 2.5},
                        ],
                        "totals": [
                            {"side": "over", "name": "Over", "price": -110, "point": 47.5},
                            {"side": "under", "name": "Under", "price": -110, "point": 47.5},
                        ],
                        "h2h": [
                            {"side": "away", "name": "Kansas City Chiefs", "price": -125, "point": None},
                            {"side": "home", "name": "Buffalo Bills", "price": 105, "point": None},
                        ],
                    },
                },
            },
        }
    ]