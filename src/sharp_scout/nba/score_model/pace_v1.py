"""Production Pace of Play qualification (v1 — matches main card rules)."""

from __future__ import annotations

from typing import Any

from sharp_scout.config import get_settings

MIN_GAP = 3.0


def pace_min_gap_pts(**_kwargs: Any) -> float:
    """Official card uses fixed 3.0 pt injury-adjusted gap (v1)."""
    return float(getattr(get_settings(), "nba_pace_min_gap_pts", MIN_GAP))


def min_team_games_for_matchup(engine: Any | None, home: str, away: str) -> int:
    tg = getattr(engine, "team_games", None) or {}
    return min(int(tg.get(home) or 0), int(tg.get(away) or 0))


def injury_adj_pace_picks(
    snap: dict[str, Any],
    *,
    home: str,
    away: str,
    min_gap: float | None = None,
    engine: Any | None = None,
    require_raw_gap: bool = False,
) -> list[dict[str, Any]]:
    from sharp_scout.nba.score_model.official_pace import _format_spread_pick

    _ = engine, require_raw_gap
    gap_bar = float(min_gap if min_gap is not None else pace_min_gap_pts())
    lines = snap.get("lines") or {}
    cs, ct = lines.get("consensus_spread_home"), lines.get("consensus_total")
    pm_i = float(
        snap.get("injury_margin") if snap.get("injury_margin") is not None else snap.get("margin") or 0
    )
    pt_i = float(
        snap.get("injury_total") if snap.get("injury_total") is not None else snap.get("total") or 0
    )
    picks: list[dict[str, Any]] = []
    if cs is not None:
        edge = pm_i + float(cs)
        if abs(edge) >= gap_bar:
            side = "home" if edge > 0 else "away"
            picks.append(
                {
                    "kind": "spread",
                    "pick": _format_spread_pick(home, away, float(cs), edge),
                    "side": side,
                    "line": float(cs) if side == "home" else -float(cs),
                    "gap": abs(edge),
                    "signed_gap": edge,
                }
            )
    if ct is not None:
        edge_t = pt_i - float(ct)
        if abs(edge_t) >= gap_bar:
            side = "over" if edge_t > 0 else "under"
            label = "Over" if edge_t > 0 else "Under"
            picks.append(
                {
                    "kind": "total",
                    "pick": f"{away} @ {home}: {label} {float(ct):g}",
                    "side": side,
                    "line": float(ct),
                    "gap": abs(edge_t),
                    "signed_gap": edge_t,
                }
            )
    return picks


def raw_qualifies(snap: dict[str, Any], *, home: str, away: str, pick: dict[str, Any], min_gap: float) -> bool:
    """True if raw model gap also clears the bar (injury-only flag helper)."""
    lines = snap.get("lines") or {}
    cs, ct = lines.get("consensus_spread_home"), lines.get("consensus_total")
    raw_m = float(snap.get("margin") or 0)
    raw_t = float(snap.get("total") or 0)
    if pick.get("kind") == "spread" and cs is not None:
        return abs(raw_m + float(cs)) >= min_gap
    if pick.get("kind") == "total" and ct is not None:
        return abs(raw_t - float(ct)) >= min_gap
    return True


def pace_display_pick_from_snapshot(
    snap: dict[str, Any],
    *,
    home: str,
    away: str,
    min_gap: float | None = None,
    engine: Any | None = None,
) -> dict[str, Any] | None:
    picks = injury_adj_pace_picks(snap, home=home, away=away, min_gap=min_gap, engine=engine)
    if not picks:
        return None
    return max(picks, key=lambda x: float(x.get("gap") or 0))


def recommended_unit_fraction(
    snap: dict[str, Any],
    pick: dict[str, Any],
    *,
    home: str,
    away: str,
    engine: Any | None,
) -> float:
    """v1 sizing hint only (not executed)."""
    settings = get_settings()
    if not getattr(settings, "nba_pace_half_unit_sizing_enabled", True):
        return 1.0
    gate = int(getattr(settings, "nba_pace_early_season_team_games", 15))
    min_gap = pace_min_gap_pts()
    half = 0.5
    if engine is not None and min_team_games_for_matchup(engine, home, away) < gate:
        return half
    if float(pick.get("gap") or 0) >= float(getattr(settings, "nba_pace_large_gap_warn_pts", 7.0)):
        return half
    if not raw_qualifies(snap, home=home, away=away, pick=pick, min_gap=min_gap):
        return half
    return 1.0
