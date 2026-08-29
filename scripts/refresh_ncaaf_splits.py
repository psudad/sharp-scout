#!/usr/bin/env python3
"""Refresh NCAAF stage cards from cached games + live Action Network splits.

Use when Odds API is unavailable but we still need updated public/money/diff
columns and market-correct hybrid picks on the board.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import ARTIFACTS_DIR, DATA_DIR  # noqa: E402
from sharp_scout.data.action_network import ActionNetworkClient  # noqa: E402
from sharp_scout.ledger.tracker import append_stage_cards, load_ledger  # noqa: E402
from sharp_scout.phase2.monte_carlo import simulate_game  # noqa: E402
from sharp_scout.sports import NCAAF  # noqa: E402
from sharp_scout.site.build import build_site  # noqa: E402
from sharp_scout.stage_picks import STAGE_MARKETS, build_slate_stage_picks  # noqa: E402


def _load_signals() -> dict:
    for path in (
        ROOT / "docs" / "latest_ncaaf_signals.json",
        ARTIFACTS_DIR / NCAAF.artifact_name,
    ):
        if path.exists():
            return json.loads(path.read_text())
    raise SystemExit("No latest_ncaaf_signals.json found — run a full pipeline first.")


def _rebuild_events(games: list[dict], signals: list[dict]) -> list[dict]:
    """Rebuild minimal Odds API-shaped events from cached edge rows."""
    events: dict[str, dict] = {}
    for g in games:
        eid = str(g["event_id"])
        events[eid] = {
            "event_id": eid,
            "sport": "ncaaf",
            "home_team": g["home_team"],
            "away_team": g["away_team"],
            "commence_time": g.get("commence_time"),
            "bookmakers": {},
        }

    # Keep best price per (event, book, market, side) for sharp + soft books.
    best: dict[tuple[str, str, str, str], dict] = {}
    for s in signals:
        eid = str(s.get("event_id") or "")
        if eid not in events:
            continue
        book = str(s.get("sharp_book") or s.get("book") or "")
        market = str(s.get("market") or "")
        side = str(s.get("side") or "")
        if not book or not market or not side:
            continue
        key = (eid, book, market, side)
        row = {
            "side": side,
            "price": s.get("price"),
            "point": s.get("line"),
            "name": side,
        }
        prev = best.get(key)
        if prev is None or (s.get("edge") or 0) > (prev.get("_edge") or 0):
            row["_edge"] = s.get("edge")
            best[key] = row

    for (eid, book, market, side), row in best.items():
        row = {k: v for k, v in row.items() if k != "_edge"}
        bm = events[eid]["bookmakers"].setdefault(
            book,
            {
                "key": book,
                "title": book,
                "is_sharp": book in ("pinnacle", "circa", "circa_sports", "betfair_ex_eu"),
                "markets": defaultdict(list),
            },
        )
        outs = bm["markets"][market]
        if not any(o.get("side") == side and o.get("point") == row.get("point") for o in outs):
            outs.append(row)

    out = []
    for ev in events.values():
        books = {}
        for key, bm in ev["bookmakers"].items():
            books[key] = {**bm, "markets": dict(bm["markets"])}
        ev["bookmakers"] = books
        out.append(ev)
    return out


def main() -> None:
    signals = _load_signals()
    games = signals.get("games") or []
    if not games:
        raise SystemExit("Cached signals have no games.")

    events = _rebuild_events(games, signals.get("signals") or [])
    splits = ActionNetworkClient(league="ncaaf").fetch_scoreboard(
        date=datetime.now(timezone.utc).strftime("%Y%m%d")
    )
    validated = [s for s in (signals.get("plays") or []) if s.get("filter_passed")]
    if not validated:
        validated = [s for s in (signals.get("signals") or []) if s.get("filter_passed")]

    sims = {}
    for g in games:
        eid = str(g["event_id"])
        sims[eid] = simulate_game(
            g["home_team"],
            g["away_team"],
            float(g["mu_home"]),
            float(g["mu_away"]),
            n_sims=3000,
            seed=42,
        )

    stage_cards = build_slate_stage_picks(
        events,
        sims,
        splits,
        validated,
        markets=STAGE_MARKETS,
        sport="ncaaf",
    )

    ledger_path = DATA_DIR / NCAAF.ledger_name
    append_stage_cards(stage_cards, path=ledger_path)

    # Refresh artifact + docs copy for site builder.
    payload = {**signals, "stage_picks": stage_cards, "generated_at": datetime.now(timezone.utc).isoformat()}
    out = ARTIFACTS_DIR / NCAAF.artifact_name
    out.write_text(json.dumps(payload, indent=2, default=str))
    (ROOT / "docs" / "latest_ncaaf_signals.json").write_text(json.dumps(payload, indent=2, default=str))

    site = build_site()
    print(f"Refreshed {len(stage_cards)} stage cards from {len(games)} games")
    print(f"AN splits: {len(splits)} games")
    print(f"Site: {site}")


if __name__ == "__main__":
    main()
