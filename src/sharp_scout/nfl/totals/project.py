"""Project simulation-first totals for a live NFL slate."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from sharp_scout.config import get_settings
from sharp_scout.data.nflfastr import load_pbp
from sharp_scout.data.situational import situational_spread_adj
from sharp_scout.nfl.totals.backtest import market_line_from_event
from sharp_scout.nfl.totals.blend import blend_total
from sharp_scout.nfl.totals.rates import build_team_drive_rates, team_rates
from sharp_scout.nfl.totals.simulate import sim_result_to_dict, simulate_nfl_total
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
    w_sim = float(settings.nfl_totals_blend_weight_sim)

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
        blended = (
            blend_total(sim.sim_median, market, weight_sim=w_sim)
            if market is not None
            else sim.sim_median
        )
        lean = "over" if blended >= (market or blended) else "under"
        if market is None:
            lean = sim.sim_lean

        payload = {
            **sim_result_to_dict(sim, blended=blended),
            "projection_total": round(blended, 2),
            "sim_lean": lean,
            "label": "simulation_total",
            "home_team": home,
            "away_team": away,
            "event_id": eid,
            "market_line": market,
        }
        by_event[eid] = payload

    meta = {"blend_weight_sim": w_sim, "n_events": len(by_event)}
    return by_event, meta
