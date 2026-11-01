"""Action Network NCAAB public-betting splits for the Sharp 3 / Sharp 3.5 systems.

Reads the raw scoreboard (money % and ticket % per side, spread and moneyline), the
opening line (AN book 30) and AN's consensus line/price, then joins each AN game to the
ESPN slate row. Percentages are kept on a 0-100 scale, as in the original rules.

Auth: ``ACTION_NETWORK_TOKEN`` / ``ACTION_NETWORK_COOKIE`` when configured; if that
request returns no splits, one anonymous retry. Credentials are never logged.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import httpx

from sharp_scout.ncaam.teams import normalize_ncaam

logger = logging.getLogger(__name__)

SCOREBOARD = "https://api.actionnetwork.com/web/v2/scoreboard/publicbetting/ncaab"
OPEN_BOOK_ID = "30"
# Consensus first, then DK / FanDuel / others as AN lists them.
SPLIT_BOOK_PRIORITY = ("15", "68", "69", "75", "123", "71", "79", "3", "11", "14")
BOOK_IDS = "15,30,68,69,75,123,71,79,3,11,14"


def _headers(token: str | None, cookie: str | None) -> dict[str, str]:
    h = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Origin": "https://www.actionnetwork.com",
        "Referer": "https://www.actionnetwork.com/ncaab/public-betting",
    }
    if token:
        h["Authorization"] = token
    if cookie:
        h["Cookie"] = cookie
    return h


def _raw_games(day: date, *, token: str | None, cookie: str | None) -> tuple[list[dict[str, Any]], int]:
    params = {"bookIds": BOOK_IDS, "periods": "event", "date": day.strftime("%Y%m%d")}
    try:
        with httpx.Client(timeout=30.0, headers=_headers(token, cookie), follow_redirects=True) as c:
            resp = c.get(SCOREBOARD, params=params)
        if resp.status_code >= 400:
            return [], resp.status_code
        games = resp.json().get("games") or []
        if isinstance(games, dict):
            games = list(games.values())
        return [g for g in games if isinstance(g, dict)], resp.status_code
    except Exception as exc:  # noqa: BLE001
        logger.warning("Action Network NCAAB fetch failed for %s: %s", day, type(exc).__name__)
        return [], 0


def _pct(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _side_of(o: dict[str, Any], home_id: Any, away_id: Any) -> str | None:
    side = str(o.get("side") or "").lower()
    if side in ("home", "away"):
        return side
    if o.get("team_id") == home_id:
        return "home"
    if o.get("team_id") == away_id:
        return "away"
    return None


def _valid_sides(sides: dict[str, Any]) -> bool:
    """Both sides carry money and ticket percentages and some money has been bet."""
    if not all(
        (sides.get(s) or {}).get("money_pct") is not None and (sides.get(s) or {}).get("ticket_pct") is not None
        for s in ("home", "away")
    ):
        return False
    return (sides["home"]["money_pct"] + sides["away"]["money_pct"]) > 0 and (
        sides["home"]["ticket_pct"] + sides["away"]["ticket_pct"]
    ) > 0


def parse_game(g: dict[str, Any]) -> dict[str, Any]:
    """One AN game -> splits record (0-100 percentages)."""
    teams = {t.get("id"): t for t in (g.get("teams") or []) if isinstance(t, dict)}
    hid, aid = g.get("home_team_id"), g.get("away_team_id")
    ht, at = teams.get(hid) or {}, teams.get(aid) or {}
    out: dict[str, Any] = {
        "an_id": str(g.get("id") or ""),
        "start_time": g.get("start_time"),
        "status": g.get("status"),
        "home_name": ht.get("location") or ht.get("display_name") or "",
        "away_name": at.get("location") or at.get("display_name") or "",
        "home_display": ht.get("display_name") or "",
        "away_display": at.get("display_name") or "",
        "home_conf": ht.get("conference_type") or "",
        "away_conf": at.get("conference_type") or "",
        "num_bets": g.get("num_bets"),
        "spread": {"home": {}, "away": {}},
        "ml": {"home": {}, "away": {}},
        "open_line": {},
        "splits_source": None,
    }
    markets = g.get("markets") or {}
    order = [b for b in SPLIT_BOOK_PRIORITY if b in markets] + [
        b for b in markets if b not in SPLIT_BOOK_PRIORITY and b != OPEN_BOOK_ID
    ]
    for kind, key in (("spread", "spread"), ("moneyline", "ml")):
        for bid in order:
            ev = (markets.get(bid) or {}).get("event") or {}
            sides: dict[str, dict[str, Any]] = {}
            for o in ev.get(kind) or []:
                side = _side_of(o, hid, aid)
                if not side:
                    continue
                bi = o.get("bet_info") or {}
                sides[side] = {
                    "money_pct": _pct((bi.get("money") or {}).get("percent")),
                    "ticket_pct": _pct((bi.get("tickets") or {}).get("percent")),
                    "line": _pct(o.get("value")) if kind == "spread" else None,
                    "price": _pct(o.get("odds")),
                }
            if _valid_sides(sides):
                out[key] = sides
                if kind == "spread":
                    out["splits_source"] = f"actionnetwork:book{bid}"
                break
    open_ev = (markets.get(OPEN_BOOK_ID) or {}).get("event") or {}
    for o in open_ev.get("spread") or []:
        side = _side_of(o, hid, aid)
        if side and o.get("value") is not None:
            out["open_line"][side] = float(o["value"])
    return out


def has_splits(rec: dict[str, Any] | None) -> bool:
    if not rec:
        return False
    return _valid_sides(rec.get("spread") or {})


def fetch_splits(days: list[date], *, token: str | None = None, cookie: str | None = None) -> dict[str, Any]:
    """All AN NCAAB games for the ET days. Returns {games, auth_mode, status, n_with_money}."""
    if token is None and cookie is None:
        try:
            from sharp_scout.config import get_settings

            st = get_settings()
            token, cookie = st.action_network_token or None, st.action_network_cookie or None
        except Exception:  # noqa: BLE001
            token = cookie = None
    modes = []
    if token or cookie:
        modes.append(("token" if token else "cookie", token, cookie))
    modes.append(("anonymous", None, None))
    last_status = 0
    for mode, tok, ck in modes:
        games: list[dict[str, Any]] = []
        for d in dict.fromkeys(days):
            raw, last_status = _raw_games(d, token=tok, cookie=ck)
            games.extend(parse_game(g) for g in raw)
        n_money = sum(1 for g in games if has_splits(g))
        if n_money or mode == "anonymous":
            return {"games": games, "auth_mode": mode, "status": last_status, "n_with_money": n_money}
        logger.info("Action Network %s auth returned no NCAAB splits; retrying anonymously", mode)
    return {"games": [], "auth_mode": "none", "status": last_status, "n_with_money": 0}


def _start(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def swap_sides(rec: dict[str, Any]) -> dict[str, Any]:
    """Copy of an AN record with home and away exchanged."""
    out = dict(rec)
    for a, b in (("home_name", "away_name"), ("home_display", "away_display"), ("home_conf", "away_conf")):
        out[a], out[b] = rec.get(b), rec.get(a)
    for key in ("spread", "ml", "open_line"):
        d = rec.get(key) or {}
        out[key] = {"home": d.get("away"), "away": d.get("home")}
        out[key] = {k: v for k, v in out[key].items() if v is not None}
    out["swapped"] = True
    return out


def match_to_slate(slate: list[dict[str, Any]], an_games: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """espn_id -> AN splits record. Exact team pair first, then one team + tip within 2h."""
    out: dict[str, dict[str, Any]] = {}
    norm = []
    for g in an_games:
        h = normalize_ncaam(g.get("home_name") or "") or normalize_ncaam(g.get("home_display") or "")
        a = normalize_ncaam(g.get("away_name") or "") or normalize_ncaam(g.get("away_display") or "")
        norm.append((g, h, a, _start(g.get("start_time"))))

    def close(t1: Any, t2: datetime | None) -> bool:
        if not isinstance(t1, datetime) or t2 is None:
            return True
        return abs((t1 - t2).total_seconds()) <= 7200

    used: set[str] = set()
    for row in slate:
        eid = str(row.get("espn_id") or "")
        tip = row.get("commence_time")
        hit = None
        for g, h, a, st in norm:
            if g["an_id"] in used:
                continue
            if h == row.get("home_team") and a == row.get("away_team") and close(tip, st):
                hit = g
                break
        if hit is None:
            # Neutral sites: AN sometimes lists the teams the other way round.
            for g, h, a, st in norm:
                if g["an_id"] in used:
                    continue
                if h == row.get("away_team") and a == row.get("home_team") and close(tip, st):
                    used.add(g["an_id"])
                    out[eid] = swap_sides(g)
                    break
            if eid in out:
                continue
        if hit is None:
            for g, h, a, st in norm:
                if g["an_id"] in used or st is None or not isinstance(tip, datetime):
                    continue
                if (h == row.get("home_team") or a == row.get("away_team")) and abs(
                    (tip - st).total_seconds()
                ) <= 1800:
                    hit = g
                    break
        if hit is not None:
            used.add(hit["an_id"])
            out[eid] = hit
    return out
