"""Tag price-gap paper plays with score-model agree / neutral / disagree."""

from __future__ import annotations

from typing import Any

from sharp_scout.nba.score_model.engine import V2Engine
from sharp_scout.nba.score_model.lines import snapshot_game_lines
from sharp_scout.nba.score_model.schedule_ctx import schedule_projection_kwargs
from sharp_scout.nba.score_model.state import ensure_score_engine
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc

MARGIN_NEUTRAL_PT = 0.5
TOTAL_NEUTRAL_PT = 1.0


def _model_pick_margin(proj_margin: float, spread_home: float | None) -> str | None:
    if spread_home is None:
        return None
    edge = proj_margin + float(spread_home)
    if abs(edge) < MARGIN_NEUTRAL_PT:
        return "neutral"
    return "home" if edge > 0 else "away"


def _model_pick_total(proj_total: float, close_total: float | None) -> str | None:
    if close_total is None:
        return None
    edge = proj_total - float(close_total)
    if abs(edge) < TOTAL_NEUTRAL_PT:
        return "neutral"
    return "over" if edge > 0 else "under"


def model_view_for_event(
    ev: dict[str, Any],
    *,
    engine: V2Engine | None = None,
) -> dict[str, Any]:
    engine = engine or ensure_score_engine()
    home = normalize_nba_team(str(ev.get("home_team") or ""))
    away = normalize_nba_team(str(ev.get("away_team") or ""))
    kick = parse_kickoff_utc(ev.get("commence_time"))
    lines = snapshot_game_lines(ev)
    sched = schedule_projection_kwargs(engine, home=home, away=away, kickoff=kick)
    cs = lines.get("consensus_spread_home")
    ct = lines.get("consensus_total")
    proj = engine.project(
        home,
        away,
        game_date=kick,
        consensus_spread_home=float(cs) if cs is not None else None,
        consensus_total=float(ct) if ct is not None else None,
        **sched,
    )
    cs = lines.get("consensus_spread_home")
    ct = lines.get("consensus_total")
    return {
        "proj_margin": float(proj["margin"]),
        "proj_total": float(proj["total"]),
        "consensus_spread_home": cs,
        "consensus_total": ct,
        "model_spread_side": _model_pick_margin(float(proj["margin"]), cs),
        "model_total_side": _model_pick_total(float(proj["total"]), ct),
        "margin_edge_pts": float(proj["margin"]) + float(cs) if cs is not None else None,
        "total_edge_pts": float(proj["total"]) - float(ct) if ct is not None else None,
    }


def alignment_for_play(play: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    market = str(play.get("market") or "")
    side = str(play.get("side") or "").lower()
    alignment = "neutral"
    edge_pts = None

    if market == "spreads":
        mside = view.get("model_spread_side")
        if mside == "neutral" or mside is None:
            alignment = "neutral"
        elif side == mside:
            alignment = "agree"
        else:
            alignment = "disagree"
        edge_pts = view.get("margin_edge_pts")
    elif market == "totals":
        mside = view.get("model_total_side")
        if mside == "neutral" or mside is None:
            alignment = "neutral"
        elif side == mside:
            alignment = "agree"
        else:
            alignment = "disagree"
        edge_pts = view.get("total_edge_pts")
    else:
        alignment = "n/a"

    return {
        "model_alignment": alignment,
        "model_edge_pts": edge_pts,
        "model_proj_margin": view.get("proj_margin"),
        "model_proj_total": view.get("proj_total"),
    }


def annotate_signals_with_model(
    events: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    *,
    engine: V2Engine | None = None,
) -> None:
    by_eid = {str(ev.get("event_id")): ev for ev in events if ev.get("event_id")}
    engine = engine or ensure_score_engine()
    cache: dict[str, dict[str, Any]] = {}
    for sig in signals:
        eid = str(sig.get("event_id") or "")
        ev = by_eid.get(eid)
        if not ev:
            continue
        if eid not in cache:
            cache[eid] = model_view_for_event(ev, engine=engine)
        sig.update(alignment_for_play(sig, cache[eid]))


def summarize_model_filter(ledger: dict[str, Any]) -> dict[str, Any]:
    """Graded side/total plays split by model_alignment."""
    buckets = {"agree": [], "disagree": [], "neutral": [], "n/a": []}
    for p in ledger.get("plays") or []:
        if str(p.get("status") or "") not in ("win", "loss", "push"):
            continue
        if p.get("play_type") == "prop":
            continue
        key = str(p.get("model_alignment") or "n/a")
        buckets.setdefault(key, []).append(p)

    def rec(subset: list[dict[str, Any]]) -> dict[str, Any]:
        w = sum(1 for p in subset if p.get("status") == "win")
        l = sum(1 for p in subset if p.get("status") == "loss")
        pu = sum(1 for p in subset if p.get("status") == "push")
        units = sum(float(p.get("pnl_units") or 0) for p in subset)
        return {"n": len(subset), "record": f"{w}-{l}-{pu}", "units": round(units, 2)}

    return {k: rec(v) for k, v in buckets.items() if v}
