"""End-to-end pipeline: ratings → MC → market EV → split filter."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import ARTIFACTS_DIR, get_settings
from sharp_scout.data.action_network import mock_splits
from sharp_scout.data.odds_api import OddsClient, mock_odds_events
from sharp_scout.data.situational import situational_spread_adj
from sharp_scout.db.models import Signal, TeamRating, get_session, init_db
from sharp_scout.phase1.ratings import build_power_ratings, matchup_means, ratings_as_of_now
from sharp_scout.phase2.monte_carlo import simulate_game
from sharp_scout.phase3.market import discover_edges
from sharp_scout.phase4.filters import attach_filters
from sharp_scout.utils.odds import setup_logging

logger = logging.getLogger(__name__)


def run_pipeline(
    *,
    demo: bool = False,
    persist: bool = True,
    skip_pbp: bool = False,
    update_ledger: bool = True,
    build_pages: bool = False,
    season: int | None = None,
    week: int | None = None,
    events: list[dict[str, Any]] | None = None,
    splits_date: str | None = None,
    fetch_splits: bool = True,
) -> dict[str, Any]:
    """Execute the four-phase signal pipeline.

    demo=True uses mock odds/splits and skips live API calls.
    skip_pbp=True uses neutral ratings (fast CI / no nflverse download).
    events= manual slate (preseason pasted lines); still joins Action Network splits.
    splits_date= YYYYMMDD for Action Network scoreboard when using manual odds.
    update_ledger=True appends validated plays to data/ledger.json.
    build_pages=True regenerates the docs/ GitHub Pages site.
    """
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db()

    # ── Phase 1 ──────────────────────────────────────────────
    if skip_pbp:
        from sharp_scout.phase1.ratings import _neutral_ratings

        ratings = _neutral_ratings()
        # Inject a slight edge so demo MC ≠ coin flip vs market
        from sharp_scout.phase1.ratings import TeamPower

        ratings["KC"] = TeamPower("KC", 0.08, 0.04, 0.02, 0.01, 0.4, 0.2, 0.12, 0.0, 0.12)
        ratings["BUF"] = TeamPower("BUF", 0.06, 0.05, 0.02, 0.02, 0.3, 0.25, 0.10, 0.02, 0.11)
    else:
        ratings = build_power_ratings()

    rating_rows = ratings_as_of_now(ratings)

    # ── Market + splits inputs ───────────────────────────────
    manual_mode = events is not None
    if manual_mode:
        logger.info("Manual slate: %d games (preseason / pasted odds)", len(events))
    elif demo or not settings.odds_api_key:
        if not settings.odds_api_key and not demo:
            logger.warning("ODDS_API_KEY missing — falling back to demo odds")
        events = mock_odds_events()
    else:
        try:
            events = OddsClient().fetch_odds()
        except Exception as exc:  # noqa: BLE001
            logger.error("Odds fetch failed (%s); using demo events", exc)
            events = mock_odds_events()

    if demo and not manual_mode:
        splits = mock_splits()
    elif fetch_splits:
        try:
            from sharp_scout.data.splits_board import fetch_action_network_splits

            splits = fetch_action_network_splits(date=splits_date, events=events)
            if not splits:
                logger.warning("Action Network returned no games — splits unavailable")
                splits = []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Action Network failed: %s", exc)
            splits = []
    else:
        splits = []

    # Record timestamped sharp line snapshot (feeds CLV closing lines + steam).
    if not (demo and not manual_mode):
        try:
            from sharp_scout.data.line_store import record_snapshot

            record_snapshot(events)
        except Exception as exc:  # noqa: BLE001
            logger.warning("line snapshot skipped: %s", exc)

    # Probability calibrator (identity until fit from settled history).
    from sharp_scout.analysis.calibration import load_calibrator

    calibrate = load_calibrator()

    # Matchup-interaction engine (no-op until a model is trained).
    matchup_adjuster = None
    scheme_feats: dict[str, Any] = {}
    if not skip_pbp:
        try:
            from sharp_scout.phase1.matchup_ml import load_adjuster

            matchup_adjuster = load_adjuster()
            if matchup_adjuster.ready:
                from sharp_scout.data.nflfastr import load_pbp
                from sharp_scout.phase1.scheme import build_scheme_features

                scheme_feats = build_scheme_features(load_pbp(), ratings)
                logger.info("Matchup engine active (%d teams)", len(scheme_feats))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Matchup engine skipped: %s", exc)

    # ── Phases 2–4 per event ─────────────────────────────────
    game_results: list[dict[str, Any]] = []
    all_signals: list[dict[str, Any]] = []
    sims_by_event: dict[str, Any] = {}

    for ev in events:
        home, away = ev["home_team"], ev["away_team"]
        situ = situational_spread_adj(home, away)
        means = matchup_means(
            home,
            away,
            ratings,
            home_boost=situ["home_points_boost"],
            total_adj=situ["total_adj"],
        )
        # Interaction residual on top of the additive baseline (bounded).
        if matchup_adjuster is not None and matchup_adjuster.ready and scheme_feats:
            means = matchup_adjuster.adjust_means(
                means, scheme_feats.get(home, {}), scheme_feats.get(away, {})
            )
        # Collect offered lines to refine cover grid
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
        edges = discover_edges(ev, sim, calibrate=calibrate)
        filtered = attach_filters(edges, splits)
        sims_by_event[str(ev.get("event_id"))] = sim

        game_results.append(
            {
                "event_id": ev.get("event_id"),
                "home_team": home,
                "away_team": away,
                "commence_time": ev.get("commence_time").isoformat()
                if hasattr(ev.get("commence_time"), "isoformat")
                else ev.get("commence_time"),
                "mu_home": means["mu_home"],
                "mu_away": means["mu_away"],
                "model_spread": round(sim.model_spread, 2),
                "model_total": round(sim.model_total, 2),
                "p_home_win": sim.p_home_win,
                "matchup_residual": means.get("matchup_residual"),
                "situational": situ,
                "edge_count": len(edges),
                "validated": sum(1 for s in filtered if s["filter_passed"]),
            }
        )
        kickoff = (
            ev.get("commence_time").isoformat()
            if hasattr(ev.get("commence_time"), "isoformat")
            else ev.get("commence_time")
        )
        for s in filtered:
            s["kickoff"] = kickoff
            s["commence_time"] = kickoff
        all_signals.extend(filtered)

    validated = [s for s in all_signals if s["filter_passed"]]
    from sharp_scout.copy.explain import collapse_best_signals, format_play_rationale

    validated = collapse_best_signals(validated, only_passed=True)
    for s in validated:
        s["rationale"] = format_play_rationale(s)

    # ── Stage picks: independent winners per data lens ────────
    from sharp_scout.stage_picks import STAGE_MARKETS, build_slate_stage_picks, summarize_stage_slate

    stage_cards = build_slate_stage_picks(events, sims_by_event, splits, validated, markets=STAGE_MARKETS)
    stage_summary = summarize_stage_slate(stage_cards)

    from sharp_scout.data.splits_board import build_slate_split_boards

    split_boards = build_slate_split_boards(events, splits, sport="nfl")
    for g in game_results:
        eid = str(g.get("event_id"))
        cards_for = [c for c in stage_cards if c["event_id"] == eid]
        g["stage_cards"] = {c["market"]: c for c in cards_for}
        card = next((c for c in cards_for if c.get("market") == "spread"), cards_for[0] if cards_for else None)
        if card:
            g["stage_picks"] = card["picks"]
            g["stage_agreement"] = card["agreement"]
            g["consensus_team"] = card.get("consensus_team")
            g["hybrid_team"] = (card.get("picks") or {}).get("hybrid", {}).get("team")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "demo": demo and not manual_mode,
        "manual_slate": manual_mode,
        "splits_date": splits_date,
        "n_splits_games": len(splits),
        "n_games": len(game_results),
        "n_candidates": len(all_signals),
        "n_validated": len(validated),
        "ratings": [
            {"team": r["team"], "power": round(r["power"], 4), "off_epa": round(r["off_epa"], 4), "def_epa": round(r["def_epa"], 4)}
            for r in sorted(rating_rows, key=lambda x: -x["power"])
        ],
        "games": game_results,
        "signals": all_signals,
        "plays": validated,
        "stage_picks": stage_cards,
        "stage_summary": stage_summary,
        "split_boards": split_boards,
    }

    out_path = ARTIFACTS_DIR / "latest_signals.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("Wrote %s (%d validated plays)", out_path, len(validated))

    if persist:
        _persist(rating_rows, validated)

    if update_ledger:
        from sharp_scout.ledger.tracker import (
            append_disagreements,
            append_signals,
            append_stage_cards,
            compute_record,
        )

        if validated:
            append_signals(validated, season=season, week=week)
        if stage_cards:
            append_stage_cards(stage_cards, season=season, week=week)

        # "Why is our model wrong?" — log material model-vs-market disagreements.
        from sharp_scout.analysis.disagreement import build_disagreements

        collapsed_all = collapse_best_signals(all_signals, only_passed=False)
        disagreements = build_disagreements(collapsed_all, season=season, week=week)
        if disagreements:
            append_disagreements(disagreements)

        payload["record"] = compute_record()

    if build_pages:
        from sharp_scout.site.build import build_site

        site_path = build_site()
        payload["site"] = str(site_path)
        logger.info("Built GitHub Pages site at %s", site_path)

    return payload


def _collect_points(event: dict[str, Any], market: str) -> list[float]:
    pts: set[float] = set()
    for bm in event.get("bookmakers", {}).values():
        for o in bm.get("markets", {}).get(market, []) or []:
            if o.get("point") is not None:
                pts.add(float(o["point"]))
                pts.add(-float(o["point"]))
    # Always include defaults around offered lines
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
        logger.error("DB persist failed: %s", exc)
    finally:
        session.close()


def load_latest_artifacts() -> dict[str, Any]:
    path = ARTIFACTS_DIR / "latest_signals.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())