"""Project simulation-first totals for a live NFL slate."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from sharp_scout.config import get_settings
from sharp_scout.data.nflfastr import load_pbp
from sharp_scout.data.situational import situational_spread_adj
from sharp_scout.nfl.totals.backtest import market_line_from_event
from sharp_scout.nfl.totals.live_calibration import infer_slate_week, resolve_live_calibration
from sharp_scout.nfl.totals.live_project import apply_live_calibration
from sharp_scout.nfl.totals.rates import build_team_drive_rates, team_rates
from sharp_scout.nfl.totals.simulate import simulate_nfl_total
from sharp_scout.phase3.market import sharp_consensus
from sharp_scout.sports import NFL

logger = logging.getLogger(__name__)


def _home_spread_line(event: dict[str, Any]) -> float | None:
    sharp = sharp_consensus(event, "spreads")
    if not sharp:
        return None
    for o in sharp.get("outcomes") or []:
        if o.get("side") == "home" and o.get("point") is not None:
            return float(o["point"])
    return None


def project_nfl_totals_for_slate(
    events: list[dict[str, Any]],
    *,
    pbp: pd.DataFrame | None = None,
    skip_pbp: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return per-event totals projection payloads and slate meta."""
    settings = get_settings()

    slate_week = infer_slate_week(events)
    cal = resolve_live_calibration(before_week=slate_week)
    logger.info(
        "nfl totals live cal: bias=%.2f w_sim=%.2f n_train=%s (%s)",
        cal.bias,
        cal.blend_weight_sim,
        cal.n_training_games,
        cal.source,
    )

    if skip_pbp or pbp is None:
        if skip_pbp:
            pbp = pd.DataFrame()
        else:
            pbp = load_pbp(settings.seasons)
    rates = build_team_drive_rates(pbp)

    by_event: dict[str, dict[str, Any]] = {}
    for ev in events:
        eid = str(ev.get("event_id") or "")
        home, away = ev["home_team"], ev["away_team"]
        market = market_line_from_event(ev)
        spread = _home_spread_line(ev)
        situ = situational_spread_adj(home, away, hfa=NFL.base_hfa)
        wind = ev.get("wind")
        roof = ev.get("roof")

        hr = team_rates(rates, home)
        ar = team_rates(rates, away)
        sim = simulate_nfl_total(
            home_team=home,
            away_team=away,
            home_rates=hr,
            away_rates=ar,
            market_line=market,
            home_spread=spread,
            wind=float(wind) if wind is not None else None,
            roof=str(roof) if roof else None,
            rest_adj=float(situ.get("total_adj") or 0.0),
            n_sims=settings.nfl_totals_sim_count,
        )
        payload = apply_live_calibration(
            sim,
            bias=cal.bias,
            blend_weight_sim=cal.blend_weight_sim,
            market_line=market,
        )
        payload.update(
            {
                "label": "simulation_total",
                "home_team": home,
                "away_team": away,
                "event_id": eid,
                "market_line": market,
                "week": ev.get("week") or slate_week,
            }
        )
        by_event[eid] = payload

    meta = {
        "blend_weight_sim": cal.blend_weight_sim,
        "walk_forward_bias": cal.bias,
        "calibration_training_games": cal.n_training_games,
        "calibration_source": cal.source,
        "n_events": len(by_event),
    }
    return by_event, meta
