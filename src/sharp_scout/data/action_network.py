"""Action Network public betting splits client.

Uses Action Network's web scoreboard endpoints. Ticket % is often public;
money/handle % may require an authenticated session cookie (ACTION_NETWORK_COOKIE).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from sharp_scout.config import get_settings
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

BASE = "https://api.actionnetwork.com/web/v1"
SCOREBOARD = "https://api.actionnetwork.com/web/v2/scoreboard/nfl"


class ActionNetworkClient:
    def __init__(self, cookie: str | None = None) -> None:
        settings = get_settings()
        self.cookie = cookie if cookie is not None else settings.action_network_cookie

    def _headers(self) -> dict[str, str]:
        h = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Origin": "https://www.actionnetwork.com",
            "Referer": "https://www.actionnetwork.com/nfl/public-betting",
        }
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def fetch_scoreboard(self, date: str | None = None) -> list[dict[str, Any]]:
        """Fetch NFL scoreboard with odds + public betting when available.

        `date` format: YYYYMMDD. Defaults to today UTC.
        """
        params: dict[str, Any] = {"bookIds": "15,30,68,75,69,71,123"}  # major US books + consensus-ish
        if date:
            params["date"] = date
        try:
            with httpx.Client(timeout=30.0, headers=self._headers(), follow_redirects=True) as client:
                resp = client.get(SCOREBOARD, params=params)
                if resp.status_code >= 400:
                    logger.warning("Action Network scoreboard %s: %s", resp.status_code, resp.text[:200])
                    return []
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Action Network fetch failed: %s", exc)
            return []

        games = payload.get("games") or payload.get("scoreboard") or []
        if isinstance(games, dict):
            games = list(games.values())
        return [self._normalize_game(g) for g in games if isinstance(g, dict)]

    def _normalize_game(self, g: dict[str, Any]) -> dict[str, Any]:
        teams = g.get("teams") or []
        home = away = None
        for t in teams:
            abbr = normalize_team(str(t.get("abbr") or t.get("abbreviation") or t.get("name") or ""))
            is_home = t.get("is_home") or t.get("home") or (t.get("side") == "home")
            if is_home:
                home = abbr
            else:
                away = abbr
        # Fallback ordering used by some payloads: teams[0]=away, teams[1]=home
        if home is None and len(teams) >= 2:
            away = normalize_team(str(teams[0].get("abbr") or teams[0].get("name") or ""))
            home = normalize_team(str(teams[1].get("abbr") or teams[1].get("name") or ""))

        markets = self._extract_markets(g)
        return {
            "game_id": str(g.get("id") or g.get("game_id") or ""),
            "start_time": g.get("start_time") or g.get("start"),
            "home_team": home,
            "away_team": away,
            "status": g.get("status"),
            "markets": markets,
            "captured_at": datetime.now(timezone.utc),
            "raw_num_bets": g.get("num_bets") or g.get("bet_count"),
        }

    def _extract_markets(self, g: dict[str, Any]) -> dict[str, Any]:
        """Pull ticket/money % and line history from nested odds / consensus blocks."""
        out: dict[str, Any] = {
            "spread": {},
            "total": {},
            "moneyline": {},
            "line_history": [],
        }

        # Consensus / public betting block (shape varies by AN version)
        consensus = g.get("consensus") or g.get("public_betting") or {}
        odds_list = g.get("odds") or []

        # Prefer explicit public betting fields when present
        for market_key, dest in (("spread", "spread"), ("total", "total"), ("ml", "moneyline"), ("moneyline", "moneyline")):
            block = consensus.get(market_key) or {}
            if not block and isinstance(odds_list, list):
                for o in odds_list:
                    if (o.get("type") or o.get("market") or "").lower() in {market_key, dest}:
                        block = o
                        break
            if not block:
                continue
            out[dest] = {
                "home_bet_pct": _pct(block.get("home_bet_percentage") or block.get("home_tickets") or block.get("bet_home")),
                "away_bet_pct": _pct(block.get("away_bet_percentage") or block.get("away_tickets") or block.get("bet_away")),
                "home_money_pct": _pct(block.get("home_money_percentage") or block.get("home_money") or block.get("money_home")),
                "away_money_pct": _pct(block.get("away_money_percentage") or block.get("away_money") or block.get("money_away")),
                "over_bet_pct": _pct(block.get("over_bet_percentage") or block.get("bet_over")),
                "under_bet_pct": _pct(block.get("under_bet_percentage") or block.get("bet_under")),
                "over_money_pct": _pct(block.get("over_money_percentage") or block.get("money_over")),
                "under_money_pct": _pct(block.get("under_money_percentage") or block.get("money_under")),
                "num_bets": block.get("num_bets") or block.get("bet_count") or g.get("num_bets"),
                "open_line": block.get("open") or block.get("open_line"),
                "current_line": block.get("line") or block.get("current_line"),
            }

        # Line history if present
        hist = g.get("line_history") or g.get("history") or []
        if isinstance(hist, list):
            out["line_history"] = hist

        return out


def _pct(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    # Action sometimes returns 0-1, sometimes 0-100
    if x <= 1.0:
        return x
    return x / 100.0


def mock_splits() -> list[dict[str, Any]]:
    return [
        {
            "game_id": "demo-kc-buf",
            "home_team": "BUF",
            "away_team": "KC",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "status": "scheduled",
            "captured_at": datetime.now(timezone.utc),
            "raw_num_bets": 12400,
            "markets": {
                "spread": {
                    "home_bet_pct": 0.72,
                    "away_bet_pct": 0.28,
                    "home_money_pct": 0.41,
                    "away_money_pct": 0.59,
                    "num_bets": 12400,
                    "open_line": -1.5,
                    "current_line": -2.5,
                },
                "total": {
                    "over_bet_pct": 0.61,
                    "under_bet_pct": 0.39,
                    "over_money_pct": 0.55,
                    "under_money_pct": 0.45,
                    "num_bets": 9800,
                    "open_line": 48.5,
                    "current_line": 47.5,
                },
                "moneyline": {},
                "line_history": [
                    {"market": "spread", "line": -1.5, "ts": "open"},
                    {"market": "spread", "line": -2.5, "ts": "current"},
                ],
            },
        }
    ]