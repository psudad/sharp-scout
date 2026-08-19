"""NCAAF 4-phase pipeline: cfbfastR ratings → MC → Odds API EV → AN splits."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sharp_scout.config import ARTIFACTS_DIR, DATA_DIR, get_settings
from sharp_scout.data.action_network import ActionNetworkClient, mock_ncaaf_splits
from sharp_scout.data.cfbfastr import load_cfb_pbp
from sharp_scout.data.odds_api import OddsClient, mock_ncaaf_odds_events
from sharp_scout.data.situational import NCAAF_STADIUMS, situational_spread_adj
from sharp_scout.db.models import Signal, TeamRating, get_session, init_db
from sharp_scout.phase1.ratings import (
    TeamPower,
    build_power_ratings,
    matchup_means,
    ratings_as_of_now,
)
from sharp_scout.phase2.monte_carlo import simulate_game
from sharp_scout.phase3.market import discover_edges
from sharp_scout.phase4.filters import attach_filters
from sharp_scout.sports import NCAAF
from sharp_scout.utils.odds import setup_logging
from sharp_scout.utils.teams import NCAAF_DEMO_TEAMS

logger = logging.getLogger(__name__)


def _demo_ratings() -> dict[str, TeamPower]:
    ratings = {
        t: TeamPower(t, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        for t in NCAAF_DEMO_TEAMS
    }
    ratings["ALA"] = TeamPower("ALA", 0.10, 0.05, 0.03, 0.02, 0.5, 0.2, 0.14, 0.02, 0.15)
    ratings["UGA"] = TeamPower("UGA", 0.08, 0.07, 0.02, 0.03, 0.4, 0.3, 0.11, 0.01, 0.15)
    ratings["OSU"] = TeamPower("OSU", 0.09, 0.04, 0.02, 0.01, 0.45, 0.2, 0.12, 0.02, 0.13)
    ratings["MICH"] = TeamPower("MICH", 0.05, 0.06, 0.01, 0.02, 0.3, 0.25, 0.08, 0.01, 0.11)
    return ratings


def run_ncaaf_pipeline(
    *,
    demo: bool = False,
    persist: bool = True,
    skip_pbp: bool = False,
    update_ledger: bool = True,
    build_pages: bool = False,
    season: int | None = None,
    week: int | None = None,
) -> dict[str, Any]:
    """Same sequence as NFL: ratings → Monte Carlo → market EV → split filter."""
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db()
    sport = NCAAF

    if skip_pbp or demo:
        ratings = _demo_ratings()
    else:
        pbp = load_cfb_pbp(settings.seasons if season is None else [season])
        ratings = build_power_ratings(pbp)
        if not ratings:
            logger.warning("Empty CFB ratings — falling back to demo priors")
            ratings = _demo_ratings()

    rating_rows = ratings_as_of_now(ratings)

    if demo or not settings.odds_api_key:
        if not settings.odds_api_key and not demo:
            logger.warning("ODDS_API_KEY missing — NCAAF demo odds")
        events = mock_ncaaf_odds_events()
    else:
        try:
            events = OddsClient(sport="ncaaf").fetch_odds()
        except Exception as exc:  # noqa: BLE001
            logger.error("NCAAF odds fetch failed (%s); using demo events", exc)
            events = mock_ncaaf_odds_events()

    if demo or not events:
        splits = mock_ncaaf_splits()
    else:
        try:
            splits = ActionNetworkClient(league="ncaaf").fetch_scoreboard()
            if not splits:
                logger.warning("AN NCAAF empty — overlay mock splits where possible")
                splits = mock_ncaaf_splits()
        except Exception as exc:  # noqa: BLE001
            logger.warning("AN NCAAF failed: %s", exc)
            splits = mock_ncaaf_splits()

    game_results: list[dict[str, Any]] = []
    all_signals: list[dict[str, Any]] = []
    sims_by_event: dict[str, Any] = {}

    for ev in events:
        home, away = ev["home_team"], ev["away_team"]
        situ = situational_spread_adj(
            home,
            away,
            hfa=sport.base_hfa,
            stadiums=NCAAF_STADIUMS,
        )
        means = matchup_means(
            home,
            away,
            ratings,
            home_boost=situ["home_points_boost"],
            total_adj=situ["total_adj"],
            sport="ncaaf",
        )
        spread_keys = _collect_points(ev, "spreads")
        total_keys = _collect_points(ev, "totals")
        sim = simulate_game(
            home,
            away,
            means["mu_home"],
            means["mu_away"],
            spread_keys=spread_keys or None,
            total_keys=total_keys or None,
        )
        edges = discover_edges(ev, sim)
        filtered = attach_filters(edges, splits)
        sims_by_event[str(ev.get("event_id"))] = sim
        kickoff = (
            ev.get("commence_time").isoformat()
            if hasattr(ev.get("commence_time"), "isoformat")
            else ev.get("commence_time")
        )
        game_results.append(
            {
                "event_id": ev.get("event_id"),
                "sport": "ncaaf",
                "home_team": home,
                "away_team": away,
                "commence_time": kickoff,
                "mu_home": means["mu_home"],
                "mu_away": means["mu_away"],
                "model_spread": sim.model_spread,
                "model_total": sim.model_total,
                "p_home_win": sim.p_home_win,
                "situational": situ,
                "edge_count": len(edges),
                "validated": sum(1 for s in filtered if s["filter_passed"]),
            }
        )
        for s in filtered:
            s["kickoff"] = kickoff
            s["commence_time"] = kickoff
            s["sport"] = "ncaaf"
        all_signals.extend(filtered)

    validated = [s for s in all_signals if s["filter_passed"]]
    validated.sort(key=lambda s: s["edge"], reverse=True)

    from sharp_scout.stage_picks import build_slate_stage_picks, summarize_stage_slate

    stage_cards = build_slate_stage_picks(events, sims_by_event, splits, validated, market="spread")
    stage_summary = summarize_stage_slate(stage_cards)
    for g in game_results:
        eid = str(g.get("event_id"))
        card = next((c for c in stage_cards if c["event_id"] == eid), None)
        if card:
            g["stage_picks"] = card["picks"]
            g["stage_agreement"] = card["agreement"]
            g["consensus_team"] = card.get("consensus_team")
            g["hybrid_team"] = (card.get("picks") or {}).get("hybrid", {}).get("team")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sport": "ncaaf",
        "demo": demo or not settings.odds_api_key,
        "n_games": len(game_results),
        "n_candidates": len(all_signals),
        "n_validated": len(validated),
        "ratings": [
            {
                "team": r["team"],
                "power": round(r["power"], 4),
                "off_epa": round(r["off_epa"], 4),
                "def_epa": round(r["def_epa"], 4),
            }
            for r in sorted(rating_rows, key=lambda x: -x["power"])
        ],
        "games": game_results,
        "signals": all_signals,
        "plays": validated,
        "stage_picks": stage_cards,
        "stage_summary": stage_summary,
    }

    out_path = ARTIFACTS_DIR / sport.artifact_name
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("Wrote %s (%d NCAAF validated plays)", out_path, len(validated))

    if persist:
        _persist(rating_rows, validated)

    if update_ledger:
        from sharp_scout.ledger.tracker import append_signals, append_stage_cards, compute_record

        ledger_path = DATA_DIR / sport.ledger_name
        if validated:
            append_signals(validated, season=season, week=week, path=ledger_path)
        if stage_cards:
            append_stage_cards(stage_cards, season=season, week=week, path=ledger_path)
        payload["record"] = compute_record(path=ledger_path)

    if build_pages:
        from sharp_scout.site.build import build_site

        payload["site"] = str(build_site())
        logger.info("Rebuilt GitHub Pages with NCAAF board")

    return payload


def _collect_points(event: dict[str, Any], market: str) -> list[float]:
    pts: set[float] = set()
    for bm in event.get("bookmakers", {}).values():
        for o in bm.get("markets", {}).get(market, []) or []:
            if o.get("point") is not None:
                pts.add(float(o["point"]))
                pts.add(-float(o["point"]))
    return sorted(pts) if pts else []


def _persist(rating_rows: list[dict], signals: list[dict]) -> None:
    session = get_session()
    try:
        for r in rating_rows:
            session.add(TeamRating(**r))
        now = datetime.now(timezone.utc)
        for s in signals:
            session.add(
                Signal(
                    created_at=now,
                    event_id=s["event_id"],
                    market=s["market"],
                    side=s["side"],
                    line=s.get("line"),
                    book=s["book"],
                    price=s["price"],
                    p_true=s["p_true"],
                    p_mkt=s.get("p_mkt"),
                    edge=s["edge"],
                    filter_passed=s["filter_passed"],
                    filter_notes=" | ".join(s.get("filter_notes") or []),
                    tier=s.get("tier") or "candidate",
                    rationale=s.get("rationale") or "",
                )
            )
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.error("NCAAF DB persist failed: %s", exc)
    finally:
        session.close()


def load_latest_ncaaf() -> dict[str, Any]:
    path = ARTIFACTS_DIR / NCAAF.artifact_name
    if not path.exists():
        return {}
    return json.loads(path.read_text())
