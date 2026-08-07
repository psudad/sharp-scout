"""Player props pipeline — usage → non-normal MC → EV → news/weather filter."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sharp_scout.config import ARTIFACTS_DIR, get_settings
from sharp_scout.data.odds_api import OddsClient, mock_odds_events
from sharp_scout.phase1.ratings import build_power_ratings, matchup_means
from sharp_scout.props.filters import apply_weather_to_usage_mult, attach_prop_filters
from sharp_scout.props.markets import build_sims_for_event, discover_prop_edges, mock_prop_event
from sharp_scout.props.simulate import CORE_PROP_MARKETS
from sharp_scout.props.usage import (
    PlayerUsage,
    apply_game_script,
    apply_matchup,
    build_usage_profiles,
    reallocate_targets,
)
from sharp_scout.utils.odds import setup_logging

logger = logging.getLogger(__name__)


def run_props_pipeline(
    *,
    demo: bool = False,
    skip_pbp: bool = False,
    events: list[dict[str, Any]] | None = None,
    update_ledger: bool = True,
    build_pages: bool = False,
    season: int | None = None,
    week: int | None = None,
    inactive: list[str] | None = None,
    wind_by_event: dict[str, float] | None = None,
    game_context: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Run props engine for upcoming (or provided) events.

    game_context: optional {event_id: {home_spread, total, home_mu, away_mu}}
    from the side pipeline so game script ties to team projections.
    """
    settings = get_settings()
    setup_logging(settings.log_level)
    inactive = inactive if inactive is not None else settings.inactive_list
    wind_by_event = wind_by_event or {}
    game_context = game_context or {}

    if skip_pbp or demo:
        from sharp_scout.props.usage import _demo_usage

        profiles = _demo_usage()
    else:
        profiles = build_usage_profiles()

    if inactive:
        # Reallocate per team mentioned
        teams = {profiles[k].team for k in profiles}
        for team in teams:
            profiles = reallocate_targets(profiles, team, inactive)

    if events is None:
        if demo or not settings.odds_api_key:
            events = [mock_prop_event(e) for e in mock_odds_events()]
        else:
            client = OddsClient()
            base = client.fetch_odds()
            events = []
            for ev in base:
                try:
                    props_ev = client.fetch_event_props(str(ev["event_id"]))
                    # Merge prop markets into side-market event shell
                    merged = dict(ev)
                    books = dict(merged.get("bookmakers") or {})
                    for bk, bm in (props_ev.get("bookmakers") or {}).items():
                        if bk not in books:
                            books[bk] = bm
                        else:
                            mk = dict(books[bk].get("markets") or {})
                            mk.update(bm.get("markets") or {})
                            books[bk] = {**books[bk], "markets": mk}
                    merged["bookmakers"] = books
                    events.append(merged)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Props fetch failed for %s: %s", ev.get("event_id"), exc)

    # Team ratings for script when context missing
    ratings = None
    try:
        if not skip_pbp and not demo:
            ratings = build_power_ratings()
    except Exception:  # noqa: BLE001
        ratings = None

    all_props: list[dict[str, Any]] = []
    event_summaries: list[dict[str, Any]] = []

    for ev in events:
        eid = str(ev.get("event_id"))
        home, away = ev["home_team"], ev["away_team"]
        ctx = game_context.get(eid) or {}
        if not ctx and ratings is not None:
            means = matchup_means(home, away, ratings)
            ctx = {
                "home_spread": means["model_spread"],
                "total": means["model_total"],
                "home_mu": means["mu_home"],
                "away_mu": means["mu_away"],
            }
        elif not ctx:
            ctx = {"home_spread": -2.5, "total": 47.5, "home_mu": 24.0, "away_mu": 22.0}

        home_spread = float(ctx.get("home_spread", 0))
        total = float(ctx.get("total", 45))

        scripted: dict[str, PlayerUsage] = {}
        for key, u in profiles.items():
            if u.team not in (home, away):
                continue
            team_spread = home_spread if u.team == home else -home_spread
            team_total = total  # shared
            s = apply_game_script(u, team_spread=team_spread, team_total=team_total, is_home=u.team == home)
            s = apply_matchup(s, opp_pass_epa_allowed=0.0)
            # Weather
            wind = wind_by_event.get(eid)
            wx = apply_weather_to_usage_mult(wind_mph=wind, precip=False)
            if s.position in ("QB", "WR", "TE"):
                s.exp_pass_att *= wx["pass_mult"]
                s.exp_pass_yards *= wx["pass_mult"]
                s.exp_targets *= wx["pass_mult"]
                s.exp_receptions *= wx["pass_mult"]
                s.exp_rec_yards *= wx["pass_mult"]
            if s.position == "RB":
                s.exp_rush_att *= wx["rush_mult"]
                s.exp_rush_yards *= wx["rush_mult"]
            scripted[key] = s

        markets = settings.prop_market_list or CORE_PROP_MARKETS
        sims = build_sims_for_event(ev, profiles, scripted, markets)
        edges = discover_prop_edges(ev, sims, ev_threshold=settings.prop_ev_threshold)
        filtered = attach_prop_filters(
            edges,
            inactive=inactive,
            wind_mph=wind_by_event.get(eid),
        )
        kickoff = (
            ev.get("commence_time").isoformat()
            if hasattr(ev.get("commence_time"), "isoformat")
            else ev.get("commence_time")
        )
        for s in filtered:
            s["kickoff"] = kickoff
            s["commence_time"] = kickoff
            s["window"] = ev.get("pregame_window")
        all_props.extend(filtered)
        event_summaries.append(
            {
                "event_id": eid,
                "home_team": home,
                "away_team": away,
                "n_sims_players": len({k[0] for k in sims}),
                "n_edges": len(edges),
                "n_validated": sum(1 for x in filtered if x["filter_passed"]),
                "script": ctx,
            }
        )

    validated = [p for p in all_props if p.get("filter_passed")]
    validated.sort(key=lambda x: x["edge"], reverse=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "demo": demo or not settings.odds_api_key,
        "play_type": "prop",
        "n_events": len(events),
        "n_candidates": len(all_props),
        "n_validated": len(validated),
        "events": event_summaries,
        "props": all_props,
        "plays": validated,
    }
    out = ARTIFACTS_DIR / "latest_props.json"
    out.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("Wrote %s (%d prop plays)", out, len(validated))

    # Merge into latest_signals for site
    side_path = ARTIFACTS_DIR / "latest_signals.json"
    if side_path.exists():
        try:
            side = json.loads(side_path.read_text())
        except json.JSONDecodeError:
            side = {}
    else:
        side = {}
    side["props"] = payload
    # Combined plays board: sides + props
    combined = list(side.get("plays") or [])
    # Drop prior props from combined if re-run
    combined = [p for p in combined if p.get("play_type") != "prop"]
    combined.extend(validated)
    side["plays"] = combined
    side["n_prop_validated"] = len(validated)
    side_path.write_text(json.dumps(side, indent=2, default=str))

    if update_ledger and validated:
        from sharp_scout.ledger.tracker import append_signals, compute_record

        ledger = append_signals(validated, season=season, week=week)
        payload["record"] = compute_record(ledger)

    if build_pages:
        from sharp_scout.site.build import build_site

        payload["site"] = str(build_site())

    return payload