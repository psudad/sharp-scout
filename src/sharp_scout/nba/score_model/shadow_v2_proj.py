"""Shadow v2 projection row (parallel to v1 paper scans)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.nba.score_model.engine_v2 import ShadowV2Engine, p_cover_home, p_over
from sharp_scout.nba.score_model.injury_adjust_v2 import (
    apply_injury_to_projection,
    injury_news_after_first_line,
)
from sharp_scout.nba.score_model.pace_v2_qualify import evaluate_pace_pick_v2
from sharp_scout.nba.score_model.schedule_ctx import schedule_projection_kwargs
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc


def shadow_v2_enabled() -> bool:
    return bool(getattr(get_settings(), "nba_pace_v2_shadow_enabled", True))


def shadow_v2_proj_row(
    engine: ShadowV2Engine,
    ev: dict[str, Any],
    *,
    at: str,
    lines: dict[str, float | None],
    prior_status: dict[str, str] | None = None,
    injury_store: dict[str, Any] | None = None,
    first_scan_at: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    home = normalize_nba_team(str(ev.get("home_team") or ""))
    away = normalize_nba_team(str(ev.get("away_team") or ""))
    kick = parse_kickoff_utc(ev.get("commence_time")) or datetime.now(timezone.utc)
    sched = {}
    if getattr(settings, "nba_v2_schedule_context", True):
        sched = schedule_projection_kwargs(engine, home=home, away=away, kickoff=kick)
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
    inj = apply_injury_to_projection(proj, home, away, prior_status=prior_status)
    snap = {
        "margin": round(proj["margin"], 2),
        "total": round(proj["total"], 2),
        "injury_margin": inj.get("injury_margin"),
        "injury_total": inj.get("injury_total"),
        "lines": lines,
        "home_absences": inj.get("home_absences") or [],
        "away_absences": inj.get("away_absences") or [],
    }
    pick, meta = evaluate_pace_pick_v2(snap, home=home, away=away, engine=engine)
    return {
        "margin": snap["margin"],
        "total": snap["total"],
        "injury_margin": snap["injury_margin"],
        "injury_total": snap["injury_total"],
        "pick": (pick or {}).get("pick") if pick else None,
        "gap": (pick or {}).get("gap") if pick else None,
        "kind": (pick or {}).get("kind") if pick else None,
        "would_be_pick": ((meta or {}).get("would_be_pick") or {}).get("pick"),
        "would_be_gap": ((meta or {}).get("would_be_pick") or {}).get("gap"),
        "exclusion_note": (meta or {}).get("exclusion_note"),
        "large_gap_warning": bool((pick or {}).get("large_gap_warning")),
        "p_cover_home_consensus": round(p_cover_home(proj["margin"], float(cs), float(proj["sd_margin"])), 4)
        if cs is not None
        else None,
        "injury_news_after_line": injury_news_after_first_line(
            first_scan_at=first_scan_at or at,
            absences=[a for a in (snap["home_absences"] + snap["away_absences"]) if a.get("kind") != "return"],
            injury_store=injury_store,
        ),
    }
