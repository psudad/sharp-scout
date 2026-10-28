"""Recompute Pace snapshots for offline replay (v1 production + v2 shadow)."""

from __future__ import annotations

from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.nba.score_model.engine import V2Engine
from sharp_scout.nba.score_model.engine_v2 import ShadowV2Engine
from sharp_scout.nba.score_model.injury_adjust import apply_team_adjustments
from sharp_scout.nba.score_model.injury_adjust_v2 import apply_team_adjustments as apply_team_adjustments_v2
from sharp_scout.nba.score_model.schedule_ctx import schedule_projection_kwargs
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc


def _injury_overlay(
    proj: dict[str, float],
    *,
    home_abs: list,
    away_abs: list,
    v2: bool,
) -> tuple[float, float]:
    if home_abs or away_abs:
        fn = apply_team_adjustments_v2 if v2 else apply_team_adjustments
        _h, _a, m, t = fn(
            float(proj["home_pts"]),
            float(proj["away_pts"]),
            home_abs=home_abs,
            away_abs=away_abs,
        )
        return round(m, 2), round(t, 2)
    return round(float(proj["margin"]), 2), round(float(proj["total"]), 2)


def recompute_v1_tip_snapshot(
    engine: V2Engine,
    *,
    home: str,
    away: str,
    kickoff: Any,
    lines: dict[str, float | None],
    injury_snap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    home = normalize_nba_team(home)
    away = normalize_nba_team(away)
    kick = parse_kickoff_utc(kickoff)
    injury_snap = injury_snap or {}
    proj = engine.project(home, away, game_date=kick)
    home_abs = injury_snap.get("home_absences") or []
    away_abs = injury_snap.get("away_absences") or []
    inj_m, inj_t = _injury_overlay(proj, home_abs=home_abs, away_abs=away_abs, v2=False)
    return {
        "margin": round(float(proj["margin"]), 2),
        "total": round(float(proj["total"]), 2),
        "injury_margin": inj_m,
        "injury_total": inj_t,
        "lines": lines,
        "home_absences": home_abs,
        "away_absences": away_abs,
    }


def recompute_v2_tip_snapshot(
    engine: ShadowV2Engine,
    *,
    home: str,
    away: str,
    kickoff: Any,
    lines: dict[str, float | None],
    injury_snap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    home = normalize_nba_team(home)
    away = normalize_nba_team(away)
    kick = parse_kickoff_utc(kickoff)
    injury_snap = injury_snap or {}
    sched = (
        schedule_projection_kwargs(engine, home=home, away=away, kickoff=kick)
        if getattr(settings, "nba_v2_schedule_context", True)
        else {}
    )
    cs = lines.get("consensus_spread_home")
    ct = lines.get("consensus_total")
    blend = getattr(settings, "nba_v2_market_blend", True)
    proj = engine.project(
        home,
        away,
        game_date=kick,
        consensus_spread_home=float(cs) if blend and cs is not None else None,
        consensus_total=float(ct) if blend and ct is not None else None,
        **sched,
    )
    home_abs = injury_snap.get("home_absences") or []
    away_abs = injury_snap.get("away_absences") or []
    inj_m, inj_t = _injury_overlay(proj, home_abs=home_abs, away_abs=away_abs, v2=True)
    return {
        "margin": round(float(proj["margin"]), 2),
        "total": round(float(proj["total"]), 2),
        "injury_margin": inj_m,
        "injury_total": inj_t,
        "lines": lines,
        "home_absences": home_abs,
        "away_absences": away_abs,
    }


# Back-compat alias
recompute_tip_snapshot = recompute_v1_tip_snapshot
