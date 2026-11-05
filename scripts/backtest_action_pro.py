#!/usr/bin/env python3
"""Grade Action Network PRO Report signals against final scores at the closing line/price.

Pulls ``/web/v2/scoreboard/proreport/{league}?week=&season=`` (needs a PRO
ACTION_NETWORK_TOKEN) into a gitignored cache, then prints win/loss/ROI per signal,
per combination and per season. Source of the PRO-tier rule in qa/pro_tier.py.

    python scripts/backtest_action_pro.py --seasons 2024 2025 2026
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR, get_settings  # noqa: E402

CACHE = DATA_DIR / "research" / "action_pro"
URL = "https://api.actionnetwork.com/web/v2/scoreboard/proreport/{lg}"
WEEKS = {"nfl": range(1, 19), "ncaaf": range(0, 17)}
BREAK_EVEN = 0.5238


def pull(seasons: list[int], *, refresh: bool = False) -> None:
    token = get_settings().action_network_token
    if not token:
        raise SystemExit("ACTION_NETWORK_TOKEN is not set (PRO token required).")
    CACHE.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0", "Authorization": token}
    with httpx.Client(headers=headers, timeout=40) as client:
        for lg, weeks in WEEKS.items():
            for season in seasons:
                for week in weeks:
                    path = CACHE / f"{lg}_{season}_w{week:02d}.json.gz"
                    if path.exists() and not refresh:
                        continue
                    params: dict[str, Any] = {"bookIds": "15,30", "periods": "event", "week": week, "season": season}
                    if lg == "ncaaf":
                        params["division"] = "FBS"
                    resp = client.get(URL.format(lg=lg), params=params)
                    if resp.status_code != 200:
                        print(f"{lg} {season} w{week}: HTTP {resp.status_code}")
                        continue
                    games = [
                        g
                        for g in resp.json().get("games") or []
                        if g.get("season") == season and g.get("status") == "complete"
                    ]
                    path.write_bytes(gzip.compress(json.dumps(games).encode()))
                    time.sleep(0.4)


def _profit(odds: float) -> float:
    return odds / 100 if odds > 0 else 100 / abs(odds)


def graded_sides() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for path in sorted(CACHE.glob("*.json.gz")):
        lg, season = path.name.split("_")[:2]
        for g in json.loads(gzip.decompress(path.read_bytes())):
            if g["id"] in seen:
                continue
            seen.add(g["id"])
            box = g.get("boxscore") or {}
            away, home = box.get("total_away_points"), box.get("total_home_points")
            if away is None or home is None:
                continue
            event = ((g.get("markets") or {}).get("15") or {}).get("event") or {}
            pro = g.get("pro_report") or {}
            for mk, sides in (("spread", ("away", "home")), ("total", ("over", "under"))):
                opts = {o["side"]: o for o in event.get(mk) or [] if o.get("value") is not None}
                if not all(s in opts for s in sides):
                    continue
                for side in sides:
                    other = sides[1] if side == sides[0] else sides[0]
                    o = opts[side]
                    line = float(o["value"])
                    if mk == "spread":
                        margin = (away - home) if side == "away" else (home - away)
                        v = margin + line
                    else:
                        v = (away + home - line) if side == "over" else (line - away - home)
                    res = "push" if v == 0 else ("win" if v > 0 else "loss")
                    odds = float(o.get("odds") or -110)
                    bi = o.get("bet_info") or {}
                    rows.append(
                        {
                            "lg": lg,
                            "season": int(season),
                            "mk": mk,
                            "side": side,
                            "res": res,
                            "pnl": 0.0 if res == "push" else (_profit(odds) if res == "win" else -1.0),
                            "tickets": (bi.get("tickets") or {}).get("percent"),
                            "money": (bi.get("money") or {}).get("percent"),
                            "sig": {x["signal_type"]: x for x in (pro.get(mk) or {}).get(side) or []},
                            "opp": {x["signal_type"]: x for x in (pro.get(mk) or {}).get(other) or []},
                        }
                    )
    return rows


def record(rows: list[dict[str, Any]]) -> str:
    w = sum(r["res"] == "win" for r in rows)
    lo = sum(r["res"] == "loss" for r in rows)
    n = w + lo
    if not n:
        return "-"
    u = sum(r["pnl"] for r in rows)
    z = (w / n - BREAK_EVEN) / math.sqrt(0.25 / n)
    return f"{w}-{lo} {w / n:.1%} {u:+.1f}u roi {u / n:+.1%} z {z:+.1f}"


def _model_edge(r: dict[str, Any]) -> float:
    return float(((r["sig"].get("power_rating_edge") or {}).get("meta") or {}).get("edge") or 0)


RULES: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
    ("Sharp Action", lambda r: "sharp_money" in r["sig"]),
    ("Big Money", lambda r: "big_bets" in r["sig"]),
    ("PRO Systems", lambda r: "pro_systems" in r["sig"]),
    ("Action model edge", lambda r: "power_rating_edge" in r["sig"]),
    ("Top experts", lambda r: "experts" in r["sig"]),
    ("Sharp + model", lambda r: "sharp_money" in r["sig"] and "power_rating_edge" in r["sig"]),
    ("Sharp + model edge>=3 (PRO tier)", lambda r: "sharp_money" in r["sig"] and _model_edge(r) >= 3),
    ("Public side >=65% tickets", lambda r: r["tickets"] is not None and r["tickets"] >= 65),
    (
        "Public side >=65%, no sharp",
        lambda r: r["tickets"] is not None and r["tickets"] >= 65 and "sharp_money" not in r["sig"],
    ),
    (
        "Money-tickets >=10 & RLM",
        lambda r: r["tickets"] is not None
        and r["money"] is not None
        and r["money"] - r["tickets"] >= 10
        and ((r["sig"].get("sharp_money") or {}).get("meta") or {}).get("reverse_line_moves", 0) >= 1,
    ),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025, 2026])
    ap.add_argument("--refresh", action="store_true", help="re-download cached weeks")
    ap.add_argument("--no-pull", action="store_true", help="grade the cache only")
    args = ap.parse_args()
    if not args.no_pull:
        pull(args.seasons, refresh=args.refresh)
    rows = [r for r in graded_sides() if r["season"] in args.seasons]
    print(f"{len(rows)} graded sides | every side at the close: {record(rows)}")
    for lg in ("nfl", "ncaaf"):
        for mk in ("spread", "total"):
            print(f"\n== {lg.upper()} {mk}")
            base = [r for r in rows if r["lg"] == lg and r["mk"] == mk]
            for name, rule in RULES:
                hit = [r for r in base if rule(r)]
                seasons = " | ".join(
                    f"{s}: {record([r for r in hit if r['season'] == s])}" for s in args.seasons
                )
                print(f"  {name:34s} {record(hit):40s} [{seasons}]")


if __name__ == "__main__":
    main()
