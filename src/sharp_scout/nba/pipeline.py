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
from sharp_scout.nba.game_lines import discover_game_line_edges, game_line_edge_to_signal
from sharp_scout.nba.ledger import append_nba_signals, load_nba_ledger, save_nba_ledger, units_staked_today
from sharp_scout.nba.line_store import record_nba_snapshot
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.props import discover_prop_edges, prop_edge_to_signal
from sharp_scout.nba.report import write_paper_report
from sharp_scout.nba.staking import apply_portfolio_caps
from sharp_scout.sports import NBA

logger = logging.getLogger(__name__)


def _kickoff_iso(ev: dict[str, Any]) -> str | None:
    ct = ev.get("commence_time")
    if isinstance(ct, datetime):
        return ct.isoformat()
    return str(ct) if ct else None


def _events_in_horizon(events: list[dict[str, Any]], hours: float) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=hours)
    out = []
    for ev in events:
        ct = ev.get("commence_time")
        if isinstance(ct, str):
            ct = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        if isinstance(ct, datetime) and ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        if ct is None:
            continue
        if now <= ct <= horizon:
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
        rates = None

    record_nba_snapshot(events, sharp_only=True)

    signals: list[dict[str, Any]] = []
    for ev in events:
        kick = _kickoff_iso(ev)
        for edge in discover_game_line_edges(ev):
            signals.append(game_line_edge_to_signal(edge, kickoff=kick))

    prop_events = events
    if fetch_props and not use_demo:
        prop_events = _events_in_horizon(events, settings.nba_prop_horizon_hours)[
            : settings.nba_max_prop_events_per_run
        ]
        merged: list[dict[str, Any]] = []
        for shell in prop_events:
            eid = shell.get("event_id")
            if not eid:
                continue
            try:
                detail = client.fetch_event_props(
                    str(eid),
                    markets=",".join(settings.nba_prop_market_list),
                    regions="us,us2,eu",
                    sport=NBA.odds_sport_key,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("NBA props fetch skipped for %s: %s", eid, exc)
                continue
            merged.append(detail)
            record_nba_snapshot([detail], sharp_only=False)
        prop_events = merged
    elif use_demo:
        prop_events = events

    table = rates
    for ev in prop_events:
        kick = _kickoff_iso(ev)
        for edge in discover_prop_edges(ev, rates=table):
            signals.append(prop_edge_to_signal(edge, kickoff=kick))

    ledger = load_nba_ledger()
    signals = apply_portfolio_caps(signals, existing_today_units=units_staked_today(ledger))

    ledger_result = {"added": 0}
    if append_ledger and signals:
        ledger_result = append_nba_signals(signals)
        ledger = ledger_result["ledger"]
        finalize_nba_clv(ledger)
        save_nba_ledger(ledger)

    payload = {
        "ok": True,
        "demo": use_demo,
        "credits_mode": credits_note,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_events": len(events),
        "n_signals": len(signals),
        "signals": signals,
        "ledger_added": ledger_result.get("added", 0),
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
