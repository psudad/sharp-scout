"""Injury / rest adjustments to stage-3 score projections (ESPN only, no Odds API).

Method (see docs/nba_injury_adjust.md):
  1. ESPN injury status × weight (Out=1.0, Doubtful=0.75, Questionable=0.5, Day-to-day=0.45, Probable=0.25).
  2. Player value from season rates (ESPN by-athlete stats → nba_player_rates.json): BPM-like proxy split
     into offense / defense / pace using minutes and usage.
  3. Missing offense subtracts from that team's projected points; missing defense adds to opponent points;
     pace drag scales both teams' scoring slightly down.
  4. Returning star (was Out/Doubtful/Questionable on prior scan, now Available/Active): add half the
     offensive boost back (ratings may have been built while they sat).
  5. Per-player and per-team caps so one injury cannot dominate the slate.
"""

from __future__ import annotations

import logging
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.data.espn_nba import fetch_espn_nba_injuries
from sharp_scout.nba.score_model.injury_lag import normalize_injury_status
from sharp_scout.nba.score_model.player_impact import (
    LEAGUE_PACE,
    ROTATION_MIN_MPG,
    defense_impact_pts,
    is_season_long_absence,
    load_rates_by_team_player,
    season_gp_from_rate_row,
    offense_impact_pts,
    pace_impact_pts,
    resolve_player_rate_row,
)
from sharp_scout.nba.rosters import ESPN_NBA_SEASON_END_YEAR, resolve_player_team_for_game
from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

STATUS_WEIGHT: dict[str, float] = {
    "out": 1.0,
    "doubtful": 0.75,
    "questionable": 0.5,
    "day-to-day": 0.18,
    "probable": 0.25,
    "unknown": 0.0,
    "available": 0.0,
    "active": 0.0,
}

RETURN_PRIOR_STATUSES = frozenset({"out", "doubtful", "questionable", "day-to-day"})
RETURN_BOOST_FRAC = 0.5
MAX_TEAM_OFF_LOSS = 12.0
MAX_TEAM_DEF_LOSS = 9.0
MAX_TEAM_PACE_LOSS = 4.0
MIN_DISPLAY_IMPACT = 0.15
INJURY_STATUSES = frozenset({"out", "doubtful", "questionable", "day-to-day", "probable"})


def injury_impact_multiplier() -> float:
    """Scale per-player injury hits until enough official graded plays exist."""
    settings = get_settings()
    scale = float(getattr(settings, "nba_injury_impact_scale", 0.5))
    gate = int(getattr(settings, "nba_injury_impact_scale_full_after_graded", 50))
    if scale >= 1.0 or gate <= 0:
        return 1.0
    try:
        from sharp_scout.nba.score_model.official_pace import load_official_pace

        graded = [
            p
            for p in load_official_pace().get("plays") or []
            if str(p.get("result") or "") in ("win", "loss", "push")
        ]
        if len(graded) >= gate:
            return 1.0
    except Exception:  # noqa: BLE001
        pass
    return max(0.0, min(scale, 1.0))


def status_weight(status: str) -> float:
    norm = normalize_injury_status(status)
    if norm == "day-to-day":
        return float(getattr(get_settings(), "nba_injury_day_to_day_weight", STATUS_WEIGHT["day-to-day"]))
    return STATUS_WEIGHT.get(norm, 0.0)


def _player_row_impacts(
    row: dict[str, Any],
    *,
    weight: float,
    pace: float = LEAGUE_PACE,
) -> tuple[float, float, float]:
    if weight <= 0:
        return 0.0, 0.0, 0.0
    mult = injury_impact_multiplier()
    off = offense_impact_pts(row, pace=pace) * weight * mult
    defn = defense_impact_pts(row, pace=pace) * weight * mult
    pace_pts = pace_impact_pts(row, pace=pace) * weight * mult
    return off, defn, pace_pts


def _cap_team(off: float, defn: float, pace_pts: float) -> tuple[float, float, float]:
    return (
        min(off, MAX_TEAM_OFF_LOSS),
        min(defn, MAX_TEAM_DEF_LOSS),
        min(pace_pts, MAX_TEAM_PACE_LOSS),
    )


def scope_injuries_to_game(
    injuries: list[dict[str, Any]],
    home: str,
    away: str,
    *,
    season: int = ESPN_NBA_SEASON_END_YEAR,
) -> list[dict[str, Any]]:
    """Attach roster-verified team codes; drop players not on either roster."""
    scoped: list[dict[str, Any]] = []
    for inj in injuries:
        name = str(inj.get("player") or "").strip()
        if not name:
            continue
        team = resolve_player_team_for_game(
            name,
            home=home,
            away=away,
            reported_team=str(inj.get("team") or "") or None,
            season=season,
        )
        if not team:
            continue
        scoped.append({**inj, "team": team, "reported_team": inj.get("team")})
    return scoped


def _rotation_player(rate_row: dict[str, Any]) -> bool:
    mpg = float(rate_row.get("minutes") or rate_row.get("mpg") or 0)
    return mpg >= ROTATION_MIN_MPG


def team_absence_rows(
    team: str,
    injuries: list[dict[str, Any]],
    *,
    rates: dict[str, dict[str, Any]] | None = None,
    prior_status: dict[str, str] | None = None,
    pace: float = LEAGUE_PACE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Absences, return boosts, and season-long exclusions for one franchise code."""
    rates = rates or load_rates_by_team_player()
    prior_status = prior_status or {}
    team = normalize_nba_team(team)
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    off_sum = def_sum = pace_sum = 0.0

    for inj in injuries:
        if normalize_nba_team(str(inj.get("team") or "")) != team:
            continue
        name = str(inj.get("player") or "").strip()
        if not name:
            continue
        status = normalize_injury_status(inj.get("status"))
        pkey = f"{team}|{name.lower()}"
        rate_row = resolve_player_rate_row(name, team, rates)
        if rate_row is None:
            excluded.append(
                {
                    "player": name,
                    "team": team,
                    "status": status,
                    "status_label": str(inj.get("status") or status).strip() or status.title(),
                    "kind": "excluded_no_stats",
                    "reason": "no season stats",
                }
            )
            continue
        detail = str(inj.get("detail") or inj.get("description") or "")
        cur_gp, played = season_gp_from_rate_row(rate_row)
        if status in INJURY_STATUSES and is_season_long_absence(
            detail=detail,
            current_season_gp=cur_gp,
            played_this_season=played,
        ):
            excluded.append(
                {
                    "player": name,
                    "team": team,
                    "status": status,
                    "status_label": str(inj.get("status") or status).strip() or status.title(),
                    "kind": "excluded_season",
                    "reason": "out all season",
                }
            )
            continue

        w = status_weight(status)
        off, defn, pace_pts = _player_row_impacts(rate_row, weight=w, pace=pace)
        kind = "absence"
        if w > 0 and status in INJURY_STATUSES and _rotation_player(rate_row):
            off_sum += off
            def_sum += defn
            pace_sum += pace_pts
            rows.append(
                {
                    "player": name,
                    "team": team,
                    "status": status,
                    "status_label": str(inj.get("status") or status).strip() or status.title(),
                    "weight": round(w, 2),
                    "off_pts": round(-off, 2),
                    "def_pts": round(-defn, 2),
                    "pace_pts": round(-pace_pts, 2),
                    "margin_pts": round(-(off + defn), 2),
                    "kind": kind,
                    "minutes": round(float(rate_row.get("minutes") or 0), 1),
                }
            )
            continue

        old = normalize_injury_status(prior_status.get(pkey))
        if status in ("available", "active") and old in RETURN_PRIOR_STATUSES:
            off_f, def_f, pace_f = _player_row_impacts(
                rate_row, weight=RETURN_BOOST_FRAC, pace=pace
            )
            if max(off_f, def_f, pace_f) >= MIN_DISPLAY_IMPACT:
                off_sum -= off_f
                def_sum -= def_f
                pace_sum -= pace_f
                rows.append(
                    {
                        "player": name,
                        "team": team,
                        "status": "returning",
                        "status_label": "Returning",
                        "weight": RETURN_BOOST_FRAC,
                        "off_pts": round(off_f, 2),
                        "def_pts": round(def_f, 2),
                        "pace_pts": round(pace_f, 2),
                        "margin_pts": round(off_f + def_f, 2),
                        "kind": "return",
                    }
                )

    return rows, excluded


def apply_team_adjustments(
    home_pts: float,
    away_pts: float,
    *,
    home_abs: list[dict[str, Any]],
    away_abs: list[dict[str, Any]],
) -> tuple[float, float, float, float]:
    """Return adjusted home_pts, away_pts, margin, total."""
    h_off = sum(-float(a.get("off_pts") or 0) for a in home_abs if a.get("kind") != "return")
    h_off -= sum(float(a.get("off_pts") or 0) for a in home_abs if a.get("kind") == "return")
    a_off = sum(-float(a.get("off_pts") or 0) for a in away_abs if a.get("kind") != "return")
    a_off -= sum(float(a.get("off_pts") or 0) for a in away_abs if a.get("kind") == "return")

    h_def = sum(-float(a.get("def_pts") or 0) for a in home_abs if a.get("kind") != "return")
    h_def -= sum(float(a.get("def_pts") or 0) for a in home_abs if a.get("kind") == "return")
    a_def = sum(-float(a.get("def_pts") or 0) for a in away_abs if a.get("kind") != "return")
    a_def -= sum(float(a.get("def_pts") or 0) for a in away_abs if a.get("kind") == "return")

    h_off, _h_def_c, _ = _cap_team(h_off, h_def, 0)
    a_off, _a_def_c, _ = _cap_team(a_off, a_def, 0)
    h_def = min(h_def, MAX_TEAM_DEF_LOSS)
    a_def = min(a_def, MAX_TEAM_DEF_LOSS)

    pace_drag = min(
        sum(-float(a.get("pace_pts") or 0) for a in home_abs + away_abs),
        MAX_TEAM_PACE_LOSS * 2,
    )
    pace_factor = max(1.0 - pace_drag / 120.0, 0.94)

    home_adj = home_pts - h_off + a_def
    away_adj = away_pts - a_off + h_def
    home_adj *= pace_factor
    away_adj *= pace_factor
    margin = home_adj - away_adj
    total = home_adj + away_adj
    return home_adj, away_adj, margin, total


def build_game_injury_bundle(
    home: str,
    away: str,
    *,
    injuries: list[dict[str, Any]] | None = None,
    prior_status: dict[str, str] | None = None,
    rates: dict[str, dict[str, Any]] | None = None,
    pace: float = LEAGUE_PACE,
) -> dict[str, Any]:
    injuries = injuries if injuries is not None else fetch_espn_nba_injuries()
    scoped = scope_injuries_to_game(injuries, home, away)
    home_abs, home_ex = team_absence_rows(
        home, scoped, rates=rates, prior_status=prior_status, pace=pace
    )
    away_abs, away_ex = team_absence_rows(
        away, scoped, rates=rates, prior_status=prior_status, pace=pace
    )
    return {
        "home_absences": home_abs,
        "away_absences": away_abs,
        "home_excluded": home_ex,
        "away_excluded": away_ex,
        "injury_refreshed_at": None,
    }


def apply_injury_to_projection(
    base: dict[str, float],
    home: str,
    away: str,
    *,
    injuries: list[dict[str, Any]] | None = None,
    prior_status: dict[str, str] | None = None,
    rates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    bundle = build_game_injury_bundle(
        home, away, injuries=injuries, prior_status=prior_status, rates=rates
    )
    home_pts, away_pts, margin, _total_from_margin = apply_team_adjustments(
        float(base["home_pts"]),
        float(base["away_pts"]),
        home_abs=bundle["home_absences"],
        away_abs=bundle["away_absences"],
    )
    th = base.get("total_home_pts")
    ta = base.get("total_away_pts")
    if th is not None and ta is not None:
        _h2, _a2, _m2, injury_total = apply_team_adjustments(
            float(th),
            float(ta),
            home_abs=bundle["home_absences"],
            away_abs=bundle["away_absences"],
        )
    else:
        injury_total = _total_from_margin
    return {
        **bundle,
        "injury_home_pts": round(home_pts, 2),
        "injury_away_pts": round(away_pts, 2),
        "injury_margin": round(margin, 2),
        "injury_total": round(injury_total, 2),
    }


def injury_news_after_first_line(
    *,
    first_scan_at: str | None,
    absences: list[dict[str, Any]],
    injury_store: dict[str, Any] | None = None,
) -> bool:
    """True when a listed absence has an injury-lag detection after the first line snapshot."""
    if not first_scan_at or not absences:
        return False
    from sharp_scout.utils.kickoff import parse_kickoff_utc

    first = parse_kickoff_utc(first_scan_at)
    if first is None:
        return False
    store = injury_store or {}
    entries = store.get("entries") or []
    names = {str(a.get("player") or "").lower() for a in absences}
    for entry in entries:
        if str(entry.get("player") or "").lower() not in names:
            continue
        det = parse_kickoff_utc(entry.get("detected_at"))
        if det and det > first:
            return True
    return False


def format_absence_line(team: str, row: dict[str, Any]) -> str:
    """Display: 'PHI without Embiid (Out): -4.1 pts' (margin-oriented)."""
    name = row.get("player") or "?"
    label = row.get("status_label") or row.get("status") or "?"
    if row.get("kind") == "excluded_season":
        return f"Excluded: {name} ({label}) — out all season (already in team ratings)"
    if row.get("kind") == "excluded_no_stats":
        return f"Excluded: {name} ({label}) — no season stats (skipped for injury adj)"
    impact = float(row.get("margin_pts") or row.get("off_pts") or 0)
    prefix = f"{team} without {name}" if row.get("kind") != "return" else f"{team} with {name} back"
    return f"{prefix} ({label}): {impact:+.1f} pts"
