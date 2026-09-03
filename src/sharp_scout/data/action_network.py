"""Action Network public betting splits client.

Primary source: scoreboard `markets[bookId].event.{spread,total,moneyline}`
outcomes, each with `bet_info.tickets.percent` and `bet_info.money.percent`.

Ticket + money % often appear without auth on books that publish them.
An `ACTION_NETWORK_COOKIE` from a logged-in Pro/EDGE session can unlock
additional books, richer `bet_info`, and line history when AN gates them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from sharp_scout.config import get_settings
from sharp_scout.sports import SportConfig, get_sport
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)

# Public-betting endpoint carries ticket/money bet_info per book.
SCOREBOARD_TMPL = "https://api.actionnetwork.com/web/v2/scoreboard/publicbetting/{league}"

# Books that commonly include public betting bet_info (DK, FanDuel, Caesars, etc.)
DEFAULT_BOOK_IDS = "15,30,255,3547,280,3,11,14,4727,4795,68,122"

_SPLIT_PCT_KEYS = (
    "home_bet_pct",
    "away_bet_pct",
    "over_bet_pct",
    "under_bet_pct",
    "home_money_pct",
    "away_money_pct",
    "over_money_pct",
    "under_money_pct",
)


def _split_row_score(row: dict[str, Any]) -> int:
    """How many split percentages a row actually carries (used to pick the better dupe)."""
    markets = row.get("markets") or {}
    score = 0
    for block in markets.values():
        if isinstance(block, dict):
            score += sum(1 for k in _SPLIT_PCT_KEYS if block.get(k) is not None)
    return score


def slate_dates_et(events: Iterable[dict[str, Any]]) -> list[str]:
    """Distinct YYYYMMDD (ET) kickoff dates for a slate, oldest first.

    Action Network buckets its scoreboard by local US date, so this is the set of dates
    we need to request to cover every game on the board.
    """
    from sharp_scout.utils.slate import ET, parse_commence

    dates: set[str] = set()
    for ev in events:
        kickoff = parse_commence(ev.get("commence_time") or ev.get("kickoff"))
        if kickoff is None:
            continue
        dates.add(kickoff.astimezone(ET).strftime("%Y%m%d"))
    return sorted(dates)


class ActionNetworkClient:
    def __init__(
        self,
        cookie: str | None = None,
        token: str | None = None,
        league: str | SportConfig = "nfl",
    ) -> None:
        settings = get_settings()
        self.cookie = cookie if cookie is not None else settings.action_network_cookie
        self.token = token if token is not None else settings.action_network_token
        self.sport = league if isinstance(league, SportConfig) else get_sport(league)
        self.league = self.sport.action_league
        self.norm_sport = self.sport.key

    @property
    def auth_mode(self) -> str:
        if self.token:
            return "token"
        if self.cookie:
            return "cookie"
        return "anonymous"

    def _headers(self) -> dict[str, str]:
        h = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Origin": "https://www.actionnetwork.com",
            "Referer": self.sport.action_referer,
        }
        # Bearer JWT is the reliable path for money %; cookie is a fallback.
        if self.token:
            h["Authorization"] = self.token
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def fetch_scoreboard(self, date: str | None = None) -> list[dict[str, Any]]:
        """Fetch league public-betting scoreboard (ticket/money %) per book.

        `date` format: YYYYMMDD. Defaults to AN's current slate.
        """
        params: dict[str, Any] = {"bookIds": DEFAULT_BOOK_IDS, "periods": "event"}
        if date:
            params["date"] = date
        try:
            with httpx.Client(timeout=30.0, headers=self._headers(), follow_redirects=True) as client:
                url = SCOREBOARD_TMPL.format(league=self.league)
                resp = client.get(url, params=params)
                if resp.status_code >= 400:
                    logger.warning(
                        "Action Network scoreboard %s: %s", resp.status_code, resp.text[:200]
                    )
                    return []
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Action Network fetch failed: %s", exc)
            return []

        games = payload.get("games") or []
        if isinstance(games, dict):
            games = list(games.values())
        return [self._normalize_game(g) for g in games if isinstance(g, dict)]

    def fetch_scoreboard_dates(self, dates: Iterable[str]) -> list[dict[str, Any]]:
        """Fetch and merge several slate dates (YYYYMMDD).

        A dateless request only returns Action Network's single default slate, which
        cannot cover a college week spanning Thursday through Saturday. Merging per-date
        requests is what makes splits available for midweek games.
        """
        merged: dict[str, dict[str, Any]] = {}
        for date in dict.fromkeys(d for d in dates if d):
            try:
                rows = self.fetch_scoreboard(date=date)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Action Network %s fetch failed for %s: %s", self.league, date, exc)
                continue
            logger.info("Action Network %s %s: %d rows", self.league, date, len(rows))
            for row in rows:
                key = str(
                    row.get("game_id")
                    or f"{row.get('away_team')}@{row.get('home_team')}"
                )
                # Keep the richer row if the same game shows up on adjacent dates.
                if key not in merged or _split_row_score(row) > _split_row_score(merged[key]):
                    merged[key] = row
        return list(merged.values())

    def diagnose(self) -> dict[str, Any]:
        """Check cookie + whether money/ticket % are present."""
        games = self.fetch_scoreboard()
        with_money = 0
        with_tickets = 0
        samples: list[dict[str, Any]] = []
        for g in games:
            spread = (g.get("markets") or {}).get("spread") or {}
            if spread.get("home_money_pct") is not None or spread.get("away_money_pct") is not None:
                with_money += 1
            if spread.get("home_bet_pct") is not None or spread.get("away_bet_pct") is not None:
                with_tickets += 1
            if len(samples) < 3:
                samples.append(
                    {
                        "matchup": f"{g.get('away_team')}@{g.get('home_team')}",
                        "spread": spread,
                        "num_bets": g.get("raw_num_bets"),
                        "auth_mode": self.auth_mode,
                    }
                )
        return {
            "auth_mode": self.auth_mode,
            "token_configured": bool(self.token),
            "cookie_configured": bool(self.cookie),
            "cookie_length": len(self.cookie or ""),
            "n_games": len(games),
            "games_with_ticket_pct": with_tickets,
            "games_with_money_pct": with_money,
            "pro_splits_ready": with_money > 0 and with_tickets > 0,
            "samples": samples,
            "hint": (
                "Money + ticket % found — Phase 4 filter can run."
                if with_money and with_tickets
                else (
                    "No money % in response. Log into Action Network Pro/EDGE in a browser, "
                    "copy the Authorization bearer token from a scoreboard/publicbetting request "
                    "(DevTools → Network → Copy as cURL), and set ACTION_NETWORK_TOKEN "
                    "(local .env + GitHub Actions secret). Cookie auth also works as a fallback."
                )
            ),
        }

    def _normalize_game(self, g: dict[str, Any]) -> dict[str, Any]:
        teams = g.get("teams") or []
        by_id: dict[Any, dict] = {}
        for t in teams:
            by_id[t.get("id")] = t

        home_id = g.get("home_team_id")
        away_id = g.get("away_team_id")
        home_t = by_id.get(home_id) or {}
        away_t = by_id.get(away_id) or {}

        # Fallback: some payloads omit home_team_id; teams[0]=away, teams[1]=home
        if not home_t and len(teams) >= 2:
            away_t, home_t = teams[0], teams[1]
        if not home_t and teams:
            for t in teams:
                if t.get("is_home"):
                    home_t = t
                else:
                    away_t = away_t or t

        home = normalize_team(
            str(home_t.get("abbr") or home_t.get("abbreviation") or home_t.get("name") or ""),
            self.norm_sport,
        )
        away = normalize_team(
            str(away_t.get("abbr") or away_t.get("abbreviation") or away_t.get("name") or ""),
            self.norm_sport,
        )

        markets = self._extract_markets(g, home_id=home_id, away_id=away_id)
        return {
            "game_id": str(g.get("id") or g.get("game_id") or ""),
            "start_time": g.get("start_time") or g.get("start"),
            "home_team": home,
            "away_team": away,
            "status": g.get("status") or g.get("real_status"),
            "markets": markets,
            "captured_at": datetime.now(timezone.utc),
            "raw_num_bets": g.get("num_bets") or g.get("bet_count"),
            "week": g.get("week"),
            "season": (g.get("season") or {}).get("season") if isinstance(g.get("season"), dict) else g.get("season"),
        }

    def _extract_markets(
        self,
        g: dict[str, Any],
        *,
        home_id: Any = None,
        away_id: Any = None,
    ) -> dict[str, Any]:
        """Pull ticket/money % from markets[book].event.{spread,total,moneyline}."""
        out: dict[str, Any] = {
            "spread": {},
            "total": {},
            "moneyline": {},
            "line_history": [],
            "source_book_id": None,
        }

        markets = g.get("markets") or {}
        if not isinstance(markets, dict):
            return out

        # Prefer a book that actually has bet_info populated
        best_book = None
        best_score = -1
        for book_id, book in markets.items():
            event = (book or {}).get("event") or {}
            score = 0
            for mtype in ("spread", "total", "moneyline"):
                for o in event.get(mtype) or []:
                    bi = o.get("bet_info") or {}
                    if isinstance(bi, dict) and bi.get("tickets") and bi.get("money"):
                        score += 1
            if score > best_score:
                best_score = score
                best_book = book_id

        if best_book is None and markets:
            best_book = next(iter(markets))

        if best_book is None:
            return out

        out["source_book_id"] = str(best_book)
        event = (markets.get(best_book) or {}).get("event") or {}

        out["spread"] = self._from_sides(
            event.get("spread") or [],
            kind="spread",
            home_id=home_id,
            away_id=away_id,
        )
        out["moneyline"] = self._from_sides(
            event.get("moneyline") or [],
            kind="moneyline",
            home_id=home_id,
            away_id=away_id,
        )
        out["total"] = self._from_totals(event.get("total") or [])

        # Open vs current: AN sometimes embeds open in edge/meta; keep current line
        if out["spread"].get("current_line") is None:
            # home spread value is the conventional line
            for o in event.get("spread") or []:
                if (o.get("side") or "").lower() == "home" and o.get("value") is not None:
                    out["spread"]["current_line"] = float(o["value"])
                    break

        hist = g.get("line_history") or g.get("history") or []
        if isinstance(hist, list):
            out["line_history"] = hist

        return out

    def _from_sides(
        self,
        outcomes: list[dict[str, Any]],
        *,
        kind: str,
        home_id: Any,
        away_id: Any,
    ) -> dict[str, Any]:
        block: dict[str, Any] = {
            "home_bet_pct": None,
            "away_bet_pct": None,
            "home_money_pct": None,
            "away_money_pct": None,
            "num_bets": None,
            "open_line": None,
            "current_line": None,
        }
        home_line = away_line = None
        for o in outcomes:
            side = (o.get("side") or "").lower()
            team_id = o.get("team_id")
            if side not in ("home", "away"):
                if team_id is not None and team_id == home_id:
                    side = "home"
                elif team_id is not None and team_id == away_id:
                    side = "away"
                else:
                    continue
            tickets, money = _bet_info_pcts(o.get("bet_info"))
            block[f"{side}_bet_pct"] = tickets
            block[f"{side}_money_pct"] = money
            if o.get("value") is not None and kind == "spread":
                if side == "home":
                    home_line = float(o["value"])
                else:
                    away_line = float(o["value"])
        if home_line is not None:
            block["current_line"] = home_line
        elif away_line is not None:
            block["current_line"] = -away_line
        return block

    def _from_totals(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        block: dict[str, Any] = {
            "over_bet_pct": None,
            "under_bet_pct": None,
            "over_money_pct": None,
            "under_money_pct": None,
            "num_bets": None,
            "open_line": None,
            "current_line": None,
        }
        for o in outcomes:
            side = (o.get("side") or "").lower()
            if side not in ("over", "under"):
                continue
            tickets, money = _bet_info_pcts(o.get("bet_info"))
            block[f"{side}_bet_pct"] = tickets
            block[f"{side}_money_pct"] = money
            if o.get("value") is not None:
                block["current_line"] = float(o["value"])
        return block


def _bet_info_pcts(bet_info: Any) -> tuple[float | None, float | None]:
    if not isinstance(bet_info, dict):
        return None, None
    tickets = bet_info.get("tickets") or {}
    money = bet_info.get("money") or {}
    t = _pct(tickets.get("percent") if isinstance(tickets, dict) else None)
    m = _pct(money.get("percent") if isinstance(money, dict) else None)
    return t, m


def _pct(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
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


def mock_ncaaf_splits() -> list[dict[str, Any]]:
    return [
        {
            "game_id": "demo-ala-uga",
            "home_team": "UGA",
            "away_team": "ALA",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "status": "scheduled",
            "captured_at": datetime.now(timezone.utc),
            "raw_num_bets": 18600,
            "markets": {
                "spread": {
                    "home_bet_pct": 0.68,
                    "away_bet_pct": 0.32,
                    "home_money_pct": 0.44,
                    "away_money_pct": 0.56,
                    "num_bets": 18600,
                    "open_line": 1.5,
                    "current_line": 2.5,
                },
                "total": {
                    "over_bet_pct": 0.64,
                    "under_bet_pct": 0.36,
                    "over_money_pct": 0.52,
                    "under_money_pct": 0.48,
                    "num_bets": 11200,
                    "open_line": 52.5,
                    "current_line": 51.5,
                },
                "moneyline": {},
                "line_history": [
                    {"market": "spread", "line": 1.5, "ts": "open"},
                    {"market": "spread", "line": 2.5, "ts": "current"},
                ],
            },
        }
    ]