#!/usr/bin/env python3
"""ESPN-only injury + roster refresh for NBA score-model display (no Odds API)."""

from __future__ import annotations

import argparse
import sys

from sharp_scout.nba.player_rates_espn import refresh_nba_player_rates_file
from sharp_scout.nba.rosters import clear_roster_cache
from sharp_scout.nba.score_model.injury_lag import load_store, record_injury_lag_scan, save_store
from sharp_scout.config import get_settings
from sharp_scout.data.espn_nba import fetch_espn_nba_upcoming
from sharp_scout.nba.score_model.paper import load_paper_store, refresh_espn_slate_injury_scans
from sharp_scout.nba.slate_et import espn_events_for_injury_window
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc
from sharp_scout.nba.score_model.state import ensure_score_engine
from sharp_scout.site.nba_page import build_nba_page
from sharp_scout.utils.odds import setup_logging


def _lines_for_matchup(store: dict, away: str, home: str, kickoff) -> dict:
    from sharp_scout.nba.score_model.paper import _find_game_by_matchup

    g = _find_game_by_matchup(store, away, home, kickoff=kickoff)
    if not g:
        return {}
    scans = g.get("scans") or []
    if not scans:
        return {}
    return dict(scans[-1].get("lines") or {})


def _injury_lag_events_from_espn_slate() -> list[dict]:
    settings = get_settings()
    store = load_paper_store()
    out = []
    for ev in espn_events_for_injury_window(
        fetch_espn_nba_upcoming(days_ahead=2),
        horizon_hours=settings.nba_prop_horizon_hours,
    ):
        home = normalize_nba_team(str(ev.get("home_team") or ""))
        away = normalize_nba_team(str(ev.get("away_team") or ""))
        kick = ev.get("kickoff")
        lines = _lines_for_matchup(store, away, home, kick)
        out.append(
            {
                "event_id": ev.get("event_id"),
                "home_team": home,
                "away_team": away,
                "commence_time": kick,
                "bookmakers": _synthetic_books(lines),
            }
        )
    return out


def _synthetic_books(lines: dict) -> dict:
    """Minimal bookmaker shell so injury-lag line snapshots keep working without Odds API."""
    cs, ct = lines.get("consensus_spread_home"), lines.get("consensus_total")
    ps, pt = lines.get("pinnacle_spread_home"), lines.get("pinnacle_total")
    mk: dict = {"spreads": [], "totals": []}
    if cs is not None:
        mk["spreads"] = [
            {"side": "home", "point": cs, "price": -110},
            {"side": "away", "point": -float(cs), "price": -110},
        ]
    if ct is not None:
        mk["totals"] = [
            {"side": "over", "point": ct, "price": -110},
            {"side": "under", "point": ct, "price": -110},
        ]
    books = {}
    if mk["spreads"] or mk["totals"]:
        books["draftkings"] = {"key": "draftkings", "markets": mk}
    if ps is not None or pt is not None:
        pin = {"spreads": [], "totals": []}
        if ps is not None:
            pin["spreads"] = [
                {"side": "home", "point": ps, "price": -110},
                {"side": "away", "point": -float(ps), "price": -110},
            ]
        if pt is not None:
            pin["totals"] = [
                {"side": "over", "point": pt, "price": -110},
                {"side": "under", "point": pt, "price": -110},
            ]
        books["pinnacle"] = {"key": "pinnacle", "markets": pin}
    return books


def main() -> int:
    parser = argparse.ArgumentParser(description="NBA ESPN injury refresh (no Odds API)")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--no-page", action="store_true", help="Skip docs/nba.html rebuild")
    args = parser.parse_args()
    setup_logging(args.log_level)

    clear_roster_cache()
    n_rates = refresh_nba_player_rates_file()
    engine = ensure_score_engine()
    n_proj = refresh_espn_slate_injury_scans(engine=engine)
    events = _injury_lag_events_from_espn_slate()
    store = load_store()
    record_injury_lag_scan(events, store=store)
    save_store(store)
    if not args.no_page:
        build_nba_page()
    print(f"player_rates={n_rates} injury_rescans={n_proj} paper_events={len(events)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
