"""Pace of Play pick qualification (gap thresholds, raw+injury, large-gap warnings)."""

from __future__ import annotations

from typing import Any

from sharp_scout.config import get_settings


def min_team_games_for_matchup(engine: Any, home: str, away: str) -> int:
    tg = getattr(engine, "team_games", None) or {}
    return min(int(tg.get(home) or 0), int(tg.get(away) or 0))


def pace_min_gap_pts(*, engine: Any | None, home: str, away: str) -> float:
    """Configurable early-season bar (default 4.5 until ~15 team games, else 3)."""
    settings = get_settings()
    base = float(getattr(settings, "nba_pace_min_gap_pts", 3.0))
    early = float(getattr(settings, "nba_pace_early_min_gap_pts", 4.5))
    gate = int(getattr(settings, "nba_pace_early_season_team_games", 15))
    if engine is None:
        return early
    if min_team_games_for_matchup(engine, home, away) < gate:
        return early
    return base


def large_gap_warn_pts() -> float:
    return float(getattr(get_settings(), "nba_pace_large_gap_warn_pts", 7.0))


def exclude_large_gap_early(*, engine: Any | None, home: str, away: str) -> bool:
    """When True, 7+ pt gaps do not qualify for official/display picks early season."""
    settings = get_settings()
    if not getattr(settings, "nba_pace_exclude_large_gap_early", True):
        return False
    gate = int(getattr(settings, "nba_pace_early_season_team_games", 15))
    if engine is None:
        return True
    return min_team_games_for_matchup(engine, home, away) < gate


def apply_large_gap_policy(
    pick: dict[str, Any] | None,
    *,
    engine: Any | None,
    home: str,
    away: str,
) -> dict[str, Any] | None:
    if pick is None:
        return None
    if pick.get("large_gap_warning") and exclude_large_gap_early(engine=engine, home=home, away=away):
        return None
    return pick


def spread_edges(
    *,
    raw_margin: float,
    injury_margin: float,
    spread_home: float,
) -> tuple[float, float]:
    """Signed edges (positive = home covers / model favors home side)."""
    cs = float(spread_home)
    return raw_margin + cs, injury_margin + cs


def total_edges(*, raw_total: float, injury_total: float, close_total: float) -> tuple[float, float]:
    ct = float(close_total)
    return raw_total - ct, injury_total - ct


def qualifies_spread(
    *,
    raw_margin: float,
    injury_margin: float,
    spread_home: float,
    min_gap: float,
    require_raw: bool = True,
) -> tuple[bool, float, float, float]:
    raw_edge, inj_edge = spread_edges(
        raw_margin=raw_margin, injury_margin=injury_margin, spread_home=spread_home
    )
    raw_ok = abs(raw_edge) >= min_gap
    inj_ok = abs(inj_edge) >= min_gap
    ok = inj_ok and (raw_ok if require_raw else True)
    return ok, abs(inj_edge), raw_edge, inj_edge


def qualifies_total(
    *,
    raw_total: float,
    injury_total: float,
    close_total: float,
    min_gap: float,
    require_raw: bool = True,
) -> tuple[bool, float, float, float]:
    raw_edge, inj_edge = total_edges(
        raw_total=raw_total, injury_total=injury_total, close_total=close_total
    )
    raw_ok = abs(raw_edge) >= min_gap
    inj_ok = abs(inj_edge) >= min_gap
    ok = inj_ok and (raw_ok if require_raw else True)
    return ok, abs(inj_edge), raw_edge, inj_edge


def injury_adj_pace_picks(
    snap: dict[str, Any],
    *,
    home: str,
    away: str,
    min_gap: float,
    engine: Any | None = None,
    require_raw_gap: bool = True,
) -> list[dict[str, Any]]:
    """Spread/total candidates that pass raw+injury gap rules."""
    from sharp_scout.nba.score_model.official_pace import _format_spread_pick

    lines = snap.get("lines") or {}
    cs, ct = lines.get("consensus_spread_home"), lines.get("consensus_total")
    raw_m = float(snap.get("margin") or 0)
    raw_t = float(snap.get("total") or 0)
    inj_m = float(snap.get("injury_margin") if snap.get("injury_margin") is not None else raw_m)
    inj_t = float(snap.get("injury_total") if snap.get("injury_total") is not None else raw_t)
    warn = large_gap_warn_pts()
    picks: list[dict[str, Any]] = []

    if cs is not None:
        ok, gap, raw_edge, inj_edge = qualifies_spread(
            raw_margin=raw_m,
            injury_margin=inj_m,
            spread_home=float(cs),
            min_gap=min_gap,
            require_raw=require_raw_gap,
        )
        if ok:
            side = "home" if inj_edge > 0 else "away"
            picks.append(
                {
                    "kind": "spread",
                    "pick": _format_spread_pick(home, away, float(cs), inj_edge),
                    "side": side,
                    "line": float(cs) if side == "home" else -float(cs),
                    "gap": gap,
                    "signed_gap": inj_edge,
                    "raw_signed_gap": raw_edge,
                    "large_gap_warning": gap >= warn,
                }
            )
    if ct is not None:
        ok, gap, raw_edge, inj_edge = qualifies_total(
            raw_total=raw_t,
            injury_total=inj_t,
            close_total=float(ct),
            min_gap=min_gap,
            require_raw=require_raw_gap,
        )
        if ok:
            side = "over" if inj_edge > 0 else "under"
            label = "Over" if inj_edge > 0 else "Under"
            picks.append(
                {
                    "kind": "total",
                    "pick": f"{away} @ {home}: {label} {float(ct):g}",
                    "side": side,
                    "line": float(ct),
                    "gap": gap,
                    "signed_gap": inj_edge,
                    "raw_signed_gap": raw_edge,
                    "large_gap_warning": gap >= warn,
                }
            )
    _ = engine
    return picks


def large_gap_exclusion_note(
    pick: dict[str, Any],
    *,
    engine: Any | None,
    home: str,
    away: str,
) -> str | None:
    if not pick.get("large_gap_warning"):
        return None
    if not exclude_large_gap_early(engine=engine, home=home, away=away):
        return (
            f"Gap {float(pick.get('gap') or 0):.1f} pt vs market (≥ {large_gap_warn_pts():g} "
            "pt early-season warning — treat with extra skepticism)."
        )
    gate = int(getattr(get_settings(), "nba_pace_early_season_team_games", 15))
    return (
        f"Gap {float(pick.get('gap') or 0):.1f} pt vs market is ≥ {large_gap_warn_pts():g} pt "
        f"before teams have {gate} games — excluded from official Pace card "
        f"(would have been {pick.get('pick')})."
    )


def evaluate_pace_pick(
    snap: dict[str, Any],
    *,
    home: str,
    away: str,
    min_gap: float | None = None,
    engine: Any | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (official pick or None, optional meta with would_be_pick + exclusion_note)."""
    gap = min_gap if min_gap is not None else pace_min_gap_pts(engine=engine, home=home, away=away)
    picks = injury_adj_pace_picks(
        snap, home=home, away=away, min_gap=gap, engine=engine, require_raw_gap=True
    )
    if not picks:
        return None, None
    best = max(picks, key=lambda x: float(x.get("gap") or 0))
    note = large_gap_exclusion_note(best, engine=engine, home=home, away=away)
    meta = None
    if note and exclude_large_gap_early(engine=engine, home=home, away=away) and best.get(
        "large_gap_warning"
    ):
        meta = {"would_be_pick": best, "exclusion_note": note, "excluded": True}
        return None, meta
    if note and not exclude_large_gap_early(engine=engine, home=home, away=away):
        meta = {"exclusion_note": note, "large_gap_warning_only": True}
    official = apply_large_gap_policy(best, engine=engine, home=home, away=away)
    return official, meta


def pace_display_pick_from_snapshot(
    snap: dict[str, Any],
    *,
    home: str,
    away: str,
    min_gap: float | None = None,
    engine: Any | None = None,
) -> dict[str, Any] | None:
    pick, _meta = evaluate_pace_pick(
        snap, home=home, away=away, min_gap=min_gap, engine=engine
    )
    return pick
