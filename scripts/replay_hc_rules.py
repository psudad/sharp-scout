"""Replay the Nov 2026 high-confidence rules over a season's posted, settled plays.

For each settled LOCKED play in the NFL / NCAAF ledgers, reports which new rule would
have dropped it (bettable book, NFL price-only, public-side spread veto) and the record
of what survives, plus the Action PRO tier record from the PRO cache.

Ticket % for the public-side veto comes from the Action PRO cache
(``scripts/backtest_action_pro.py`` pulls it), joined on kickoff and team abbreviation.

    python scripts/replay_hc_rules.py --season 2026
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.utils.odds import expected_value
from sharp_scout.qa.pro_tier import bettable_books

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "research" / "action_pro"
LEDGERS = {"nfl": ROOT / "data" / "ledger.json", "ncaaf": ROOT / "data" / "ncaaf_ledger.json"}
_AN_MARKET = {"spreads": "spread", "totals": "total"}


def _ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _ticket_index(season: int) -> dict[str, list[tuple[float, set[str], dict[str, Any]]]]:
    idx: dict[str, list[tuple[float, set[str], dict[str, Any]]]] = defaultdict(list)
    for path in sorted(CACHE.glob(f"*_{season}_w*.json.gz")):
        lg = path.name.split("_")[0]
        for g in json.loads(gzip.decompress(path.read_bytes())):
            teams = {t["id"]: t for t in g.get("teams") or []}
            home = teams.get(g.get("home_team_id"), {})
            away = teams.get(g.get("away_team_id"), {})
            abbrs = {str(x).upper() for x in (home.get("abbr"), away.get("abbr")) if x}
            event = ((g.get("markets") or {}).get("15") or {}).get("event") or {}
            tickets: dict[str, Any] = {}
            for mk in ("spread", "total"):
                for o in event.get(mk) or []:
                    pct = ((o.get("bet_info") or {}).get("tickets") or {}).get("percent")
                    if pct is not None:
                        tickets[f"{mk}:{o['side']}"] = pct / 100
            idx[lg].append((_ts(g["start_time"]), abbrs, {"home": home.get("abbr"), "tickets": tickets}))
    return idx


def _match(idx, sport: str, play: dict[str, Any]) -> dict[str, Any] | None:
    if not play.get("kickoff"):
        return None
    t = _ts(play["kickoff"])
    names = {str(play.get("home_team") or "").upper(), str(play.get("away_team") or "").upper()}
    best = None
    for ts, abbrs, g in idx.get(sport, []):
        if abs(ts - t) <= 6 * 3600 and abbrs & names:
            if best is None or len(abbrs & names) > len(best[0]):
                best = (abbrs & names, g)
    return best[1] if best else None


def _side_tickets(g: dict[str, Any] | None, play: dict[str, Any]) -> float | None:
    if not g or play["market"] not in _AN_MARKET:
        return None
    side = play["side"]
    if play["market"] == "spreads" and side not in ("home", "away"):
        side = "home" if str(side).upper() == str(g["home"]).upper() else "away"
    return g["tickets"].get(f"{_AN_MARKET[play['market']]}:{side}")


def _record(rows: list[dict[str, Any]]) -> str:
    w = sum(r["status"] == "win" for r in rows)
    lo = sum(r["status"] == "loss" for r in rows)
    p = sum(r["status"] == "push" for r in rows)
    u = sum(float(r.get("pnl_units") or 0) for r in rows)
    return f"{w}-{lo}" + (f"-{p}" if p else "") + f"  {u:+.1f}u"


def replay(sport: str, season: int, idx) -> None:
    settings = get_settings()
    books = bettable_books(settings)
    plays = [
        p
        for p in json.loads(LEDGERS[sport].read_text())["plays"]
        if p.get("status") in ("win", "loss", "push") and (p.get("season") in (season, None))
    ]
    dropped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    kept: list[dict[str, Any]] = []
    off_book = [p for p in plays if books and str(p.get("book") or "").lower() not in books]
    matched = 0
    for p in plays:
        g = _match(idx, sport, p)
        matched += g is not None
        tk = _side_tickets(g, p)
        if sport == "nfl" and (
            p.get("p_fair") is None
            or expected_value(float(p["p_fair"]), float(p["price"])) < settings.product_nfl_min_ev_vs_fair
        ):
            dropped["NFL < +2% vs no-vig fair"].append(p)
        elif p["market"] in settings.product_public_side_veto_markets.split(",") and tk is not None and tk >= settings.product_public_side_veto_tickets:
            dropped["public spread side (>=65% tickets)"].append(p)
        elif p["market"] == "h2h":
            dropped["h2h (shadow market)"].append(p)
        else:
            kept.append(p)
    print(f"\n== {sport.upper()} {season}: {len(plays)} settled posted plays ({matched} matched to Action splits)")
    print(f"  as posted:              {_record(plays)}")
    print(f"  priced off FanDuel:     {len(off_book)} of {len(plays)}  {_record(off_book)}")
    print("  rules below assume the same line was available at FanDuel:")
    for why, rows in dropped.items():
        print(f"  dropped {why:34s} {len(rows):3d}  {_record(rows)}")
    print(f"  survivors:              {_record(kept)}")
    if sport == "ncaaf":
        tot = [p for p in kept if p["market"] == "totals"]
        u = sum(float(p.get("pnl_units") or 0) * 0.75 / float(p.get("units") or 1) for p in tot)
        print(f"  survivor totals at 0.75u: {len(tot)} plays  {u:+.1f}u")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    idx = _ticket_index(args.season)
    for sport in ("nfl", "ncaaf"):
        replay(sport, args.season, idx)


if __name__ == "__main__":
    main()
