"""Orchestrate NBA shadow scans (game lines + props) into private ledger artifacts."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.data.odds_api import OddsClient
from sharp_scout.nba.clv import finalize_nba_clv
from sharp_scout.nba.demo import demo_player_rates, mock_nba_events
from sharp_scout.nba.game_lines import (
    discover_game_line_edges,
    game_line_edge_to_signal,
    scan_game_line_opportunities,
)
from sharp_scout.nba.ledger import (
    append_nba_signals,
    filter_demo_from_signal_lists,
    kickoff_in_horizon,
    load_nba_ledger,
    merge_open_ledger_picks,
    save_nba_ledger,
    strip_demo_plays_from_ledger,
    units_staked_today,
)
from sharp_scout.nba.line_store import record_nba_snapshot
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.possible import (
    POSSIBLE_PICK_LIMIT,
    cap_props_per_game,
    finalize_possible_picks,
    opportunity_row_to_signal,
    pick_dedupe_key,
)
from sharp_scout.nba.projections import bootstrap_rates_from_prop_markets, load_rate_table
from sharp_scout.nba.props import discover_prop_edges, prop_edge_to_signal, scan_prop_opportunities
from sharp_scout.nba.report import write_paper_report
from sharp_scout.nba.settle import settle_nba_ledger
from sharp_scout.nba.staking import apply_portfolio_caps_split
from sharp_scout.sports import NBA

logger = logging.getLogger(__name__)


def _kickoff_iso(ev: dict[str, Any]) -> str | None:
    ct = ev.get("commence_time")
    if isinstance(ct, datetime):
        return ct.isoformat()
    return str(ct) if ct else None


def _events_in_horizon(events: list[dict[str, Any]], hours: float) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    out = []
    for ev in events:
        ct = ev.get("commence_time")
        if kickoff_in_horizon(ct, hours, now=now):
            out.append(ev)
    return sorted(out, key=lambda e: e.get("commence_time") or now)


def run_nba_shadow(
    *,
    demo: bool = False,
    fetch_props: bool = True,
    append_ledger: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.nba_shadow_enabled:
        return {"ok": False, "reason": "nba_shadow_disabled"}

    client = OddsClient(sport=NBA)
    use_demo = demo or not settings.odds_api_key
    credits_note = "demo" if use_demo else "live"

    if use_demo:
        events = mock_nba_events()
        rates = demo_player_rates()
    else:
        events = client.fetch_odds(markets="h2h,spreads,totals", regions="us,us2,eu")
        rates = load_rate_table()

    record_nba_snapshot(events, sharp_only=True)

    score_engine = None
    if not use_demo:
        try:
            from sharp_scout.nba.score_model.injury_lag import record_injury_lag_scan
            from sharp_scout.nba.score_model.paper import record_score_model_scan
            from sharp_scout.nba.score_model.state import ensure_score_engine

            score_engine = ensure_score_engine()
            record_score_model_scan(events, engine=score_engine)
            record_injury_lag_scan(events)
        except Exception as exc:  # noqa: BLE001
            logger.warning("NBA score/injury paper tracking skipped: %s", exc)

    line_events = (
        events
        if use_demo
        else _events_in_horizon(events, settings.nba_prop_horizon_hours)
    )

    signals: list[dict[str, Any]] = []
    scan_rows: list[dict[str, Any]] = []
    for ev in line_events:
        kick = _kickoff_iso(ev)
        for opp in scan_game_line_opportunities(ev):
            scan_rows.append({**opp, "kickoff": kick})
        for edge in discover_game_line_edges(ev):
            signals.append(game_line_edge_to_signal(edge, kickoff=kick))

    prop_diagnostics: dict[str, Any] = {
        "enabled": fetch_props,
        "horizon_hours": settings.nba_prop_horizon_hours,
        "regions": settings.nba_prop_regions,
        "events_in_horizon": len(line_events) if not use_demo else 0,
        "game_line_events_in_horizon": len(line_events) if not use_demo else 0,
        "events_fetched": 0,
        "fetch_failures": 0,
        "file_rate_players": len(rates or {}),
        "consensus_only_note": (
            "Players not listed in nba_player_rates.json are graded vs de-vigged "
            "multi-book consensus (retail book excluded). Bootstrap line projections "
            "are not used for EV."
        ),
        "lines_scanned": 0,
        "opportunities_positive_ev": 0,
        "consensus_unavailable_skips": 0,
        "consensus_only_scored": 0,
        "model_scored": 0,
        "qualified_prop_edges": 0,
        "prop_picks_pre_cap": 0,
        "prop_possible_pre_cap": 0,
    }

    file_rate_keys = set((rates or {}).keys())
    prop_scan_stats: dict[str, int] = {}

    prop_events = events
    if fetch_props and not use_demo:
        horizon_shells = _events_in_horizon(events, settings.nba_prop_horizon_hours)[
            : settings.nba_max_prop_events_per_run
        ]
        prop_diagnostics["events_in_horizon"] = len(horizon_shells)
        merged: list[dict[str, Any]] = []
        for shell in horizon_shells:
            eid = shell.get("event_id")
            if not eid:
                continue
            try:
                detail = client.fetch_event_props(
                    str(eid),
                    markets=",".join(settings.nba_prop_market_list),
                    regions=settings.nba_prop_regions,
                    sport=NBA.odds_sport_key,
                )
            except Exception as exc:  # noqa: BLE001
                prop_diagnostics["fetch_failures"] += 1
                logger.warning("NBA props fetch skipped for %s: %s", eid, exc)
                continue
            merged.append(detail)
            record_nba_snapshot([detail], sharp_only=False)
        prop_events = merged
        prop_diagnostics["events_fetched"] = len(merged)
    elif use_demo:
        prop_events = events

    prop_signals_before_caps = 0
    for ev in prop_events:
        kick = _kickoff_iso(ev)
        scan_table = dict(rates or {})
        if use_demo:
            scan_table = bootstrap_rates_from_prop_markets(scan_table, ev)
        for opp in scan_prop_opportunities(
            ev,
            rates=scan_table,
            file_rate_keys=file_rate_keys,
            stats=prop_scan_stats,
        ):
            prop_diagnostics["lines_scanned"] += 1
            if float(opp.get("edge") or 0) > 0:
                prop_diagnostics["opportunities_positive_ev"] += 1
            scan_rows.append({**opp, "kickoff": kick})
        for edge in discover_prop_edges(
            ev, rates=scan_table, file_rate_keys=file_rate_keys
        ):
            prop_diagnostics["qualified_prop_edges"] += 1
            prop_signals_before_caps += 1
            signals.append(prop_edge_to_signal(edge, kickoff=kick))

    prop_diagnostics["prop_picks_pre_cap"] = prop_signals_before_caps
    prop_diagnostics["consensus_unavailable_skips"] = prop_scan_stats.get("consensus_unavailable", 0)
    prop_diagnostics["consensus_only_scored"] = prop_scan_stats.get("consensus_only_scored", 0)
    prop_diagnostics["model_scored"] = prop_scan_stats.get("model_scored", 0)

    ledger = load_nba_ledger()
    if not use_demo:
        settle_nba_ledger(ledger)
        ledger = load_nba_ledger()
        ledger, demo_removed = strip_demo_plays_from_ledger(ledger)
        if demo_removed:
            save_nba_ledger(ledger)
            write_paper_report(ledger, nba_paths.NBA_REPORT_PATH)
    staked_today = units_staked_today(ledger)
    side_candidates = [s for s in signals if (s.get("play_type") or "side") != "prop"]
    prop_candidates = [s for s in signals if (s.get("play_type") or "") == "prop"]
    side_accepted, side_rejected = apply_portfolio_caps_split(
        side_candidates, existing_today_units=staked_today
    )
    side_units = sum(float(s.get("units") or 0) for s in side_accepted)
    prop_accepted, prop_rejected = apply_portfolio_caps_split(
        prop_candidates, existing_today_units=staked_today + side_units
    )
    signals = side_accepted + prop_accepted
    cap_rejected = side_rejected + prop_rejected

    pick_keys = {pick_dedupe_key(s) for s in signals}
    cap_rejected_keys = {pick_dedupe_key(r) for r in cap_rejected}
    near_pool: list[dict[str, Any]] = []
    for row in scan_rows:
        sig = opportunity_row_to_signal(row)
        key = pick_dedupe_key(sig)
        if key in pick_keys or key in cap_rejected_keys:
            continue
        reason = row.get("reject_reason")
        if row.get("qualified"):
            reason = reason or "Lower EV vs best qualifying line"
        elif not reason:
            reason = "Did not qualify"
        near_pool.append({**sig, "reject_reason": reason})

    for rej in cap_rejected:
        if pick_dedupe_key(rej) in pick_keys:
            continue
        near_pool.append(
            {
                **rej,
                "reject_reason": rej.get("reject_reason") or "Portfolio unit cap",
                "filter_passed": True,
            }
        )

    side_near = [c for c in near_pool if (c.get("play_type") or "side") != "prop"]
    prop_near = [c for c in near_pool if (c.get("play_type") or "") == "prop"]
    possible_signals = finalize_possible_picks(
        side_near, pick_keys=pick_keys, limit=POSSIBLE_PICK_LIMIT
    ) + finalize_possible_picks(prop_near, pick_keys=pick_keys, limit=POSSIBLE_PICK_LIMIT)

    prop_diagnostics["prop_possible_pre_cap"] = len(
        [c for c in prop_near if float(c.get("edge") or 0) > 0]
    )

    signals, possible_signals = cap_props_per_game(signals, possible_signals)

    prop_diagnostics["prop_picks"] = len([s for s in signals if s.get("play_type") == "prop"])
    prop_diagnostics["prop_possible"] = len(
        [p for p in possible_signals if p.get("play_type") == "prop"]
    )

    if not use_demo and score_engine is not None:
        try:
            from sharp_scout.nba.score_model.model_filter import annotate_signals_with_model

            annotate_signals_with_model(events, signals, engine=score_engine)
            annotate_signals_with_model(events, possible_signals, engine=score_engine)
        except Exception as exc:  # noqa: BLE001
            logger.warning("NBA model filter annotation skipped: %s", exc)

    signals_for_ledger = list(signals)
    if not use_demo:
        signals, possible_signals = filter_demo_from_signal_lists(signals, possible_signals)
        signals, possible_signals = merge_open_ledger_picks(
            signals, possible_signals, ledger, live_scan=True
        )

    ledger_result = {"added": 0}
    if append_ledger and signals_for_ledger:
        ledger_result = append_nba_signals(signals_for_ledger)
        ledger = ledger_result["ledger"]
        if not use_demo:
            ledger, demo_removed = strip_demo_plays_from_ledger(ledger)
            if demo_removed:
                save_nba_ledger(ledger)
        finalize_nba_clv(ledger)
        save_nba_ledger(ledger)
        if not use_demo:
            write_paper_report(ledger, nba_paths.NBA_REPORT_PATH)
            signals, possible_signals = merge_open_ledger_picks(
                signals, possible_signals, ledger, live_scan=True
            )
            signals, possible_signals = filter_demo_from_signal_lists(signals, possible_signals)

    payload = {
        "ok": True,
        "demo": use_demo,
        "credits_mode": credits_note,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_events": len(events),
        "n_signals": len(signals),
        "signals": signals,
        "n_possible": len(possible_signals),
        "possible_signals": possible_signals,
        "ledger_added": ledger_result.get("added", 0),
        "prop_diagnostics": prop_diagnostics,
    }

    nba_paths.NBA_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = nba_paths.NBA_ARTIFACT_DIR / "latest_signals.json"
    artifact_path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    nba_paths.NBA_LATEST_SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    nba_paths.NBA_LATEST_SIGNALS_PATH.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    if ledger.get("plays"):
        write_paper_report(ledger, nba_paths.NBA_REPORT_PATH)

    logger.info(
        "NBA shadow: events=%d signals=%d ledger_added=%d demo=%s",
        len(events),
        len(signals),
        ledger_result.get("added", 0),
        use_demo,
    )
    return payload
