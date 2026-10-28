"""Recompute Pace snapshots from engine + stored lines/injuries (no Odds API)."""

from __future__ import annotations

from typing import Any

from sharp_scout.nba.score_model.engine import V2Engine
from sharp_scout.nba.score_model.injury_adjust import apply_team_adjustments
from sharp_scout.nba.score_model.schedule_ctx import schedule_projection_kwargs
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc


def recompute_tip_snapshot(
    engine: V2Engine,
    *,
    home: str,
    away: str,
    kickoff: Any,
    lines: dict[str, float | None],
    injury_snap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fresh model margin/total/injury fields; injury lists from stored tip scan."""
    home = normalize_nba_team(home)
    away = normalize_nba_team(away)
    kick = parse_kickoff_utc(kickoff)
    injury_snap = injury_snap or {}
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
    home_abs = injury_snap.get("home_absences") or []
    away_abs = injury_snap.get("away_absences") or []
    if home_abs or away_abs:
        h, a, m, t = apply_team_adjustments(
            float(proj["home_pts"]),
            float(proj["away_pts"]),
            home_abs=home_abs,
            away_abs=away_abs,
        )
        inj_m, inj_t = round(m, 2), round(t, 2)
    else:
        inj_m = round(float(proj["margin"]), 2)
        inj_t = round(float(proj["total"]), 2)
    return {
        "margin": round(float(proj["margin"]), 2),
        "total": round(float(proj["total"]), 2),
        "injury_margin": inj_m,
        "injury_total": inj_t,
        "home_pts": round(float(proj["home_pts"]), 2),
        "away_pts": round(float(proj["away_pts"]), 2),
        "lines": lines,
        "large_gap_warning": bool(proj.get("large_gap_warning")),
        "market_gap_margin": proj.get("market_gap_margin"),
        "home_absences": home_abs,
        "away_absences": away_abs,
    }
