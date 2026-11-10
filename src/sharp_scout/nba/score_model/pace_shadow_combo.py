"""Shadow Pace v1: league efficiency correction + market blend (not official card)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR, get_settings
from sharp_scout.nba.score_model.injury_adjust import apply_team_adjustments
from sharp_scout.nba.score_model.pace_v1 import MIN_GAP, pace_min_gap_pts, require_raw_gap_v1
from sharp_scout.nba.score_model.pace_v2_qualify import qualifies_total
from sharp_scout.nba.score_model.true_close import true_close_lines_for_game
from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc

logger = logging.getLogger(__name__)

SHADOW_COMBO_PATH = DATA_DIR / "nba_pace_shadow_combo.json"
SHADOW_COMBO_RECORD_ENABLED = True


def _empty() -> dict[str, Any]:
    return {
        "version": 1,
        "notes": "Pace v1 shadow: league efficiency correction + market blend. Not published.",
        "plays": [],
        "pending": [],
        "updated_at": None,
    }


def load_shadow_combo(path: Path | None = None) -> dict[str, Any]:
    p = path or SHADOW_COMBO_PATH
    if not p.exists():
        return _empty()
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return _empty()
    raw.setdefault("plays", [])
    raw.setdefault("pending", [])
    return raw


def save_shadow_combo(store: dict[str, Any], path: Path | None = None) -> None:
    p = path or SHADOW_COMBO_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")


def shadow_combo_enabled() -> bool:
    return bool(getattr(get_settings(), "nba_pace_shadow_combo_enabled", True))


def _combo_model_weight() -> float:
    return float(getattr(get_settings(), "nba_pace_shadow_combo_blend_weight", 0.35))


def recompute_combo_projection(
    engine: Any,
    *,
    home: str,
    away: str,
    kickoff: Any,
    lines: dict[str, float | None],
    injury_snap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    home = normalize_nba_team(home)
    away = normalize_nba_team(away)
    kick = parse_kickoff_utc(kickoff) or datetime.now(timezone.utc)
    injury_snap = injury_snap or {}
    proj = engine.project(
        home,
        away,
        game_date=kick,
        league_efficiency_force=True,
    )
    home_abs = injury_snap.get("home_absences") or []
    away_abs = injury_snap.get("away_absences") or []
    if home_abs or away_abs:
        _h, _a, m, t = apply_team_adjustments(
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
        "lines": lines,
    }


def combo_total_pick(
    snap: dict[str, Any],
    *,
    home: str,
    away: str,
    model_weight: float | None = None,
) -> dict[str, Any] | None:
    lines = snap.get("lines") or {}
    ct = lines.get("consensus_total")
    if ct is None:
        return None
    raw_t = float(snap.get("total") or 0)
    inj_t = float(snap.get("injury_total") if snap.get("injury_total") is not None else raw_t)
    w = _combo_model_weight() if model_weight is None else float(model_weight)
    w = max(0.0, min(1.0, w))
    inj_for_gap = w * inj_t + (1.0 - w) * float(ct)
    ok, gap, raw_edge, inj_edge = qualifies_total(
        raw_total=raw_t,
        injury_total=inj_for_gap,
        close_total=float(ct),
        min_gap=pace_min_gap_pts(),
        require_raw=require_raw_gap_v1(),
    )
    if not ok:
        return None
    side = "over" if inj_edge > 0 else "under"
    label = "Over" if inj_edge > 0 else "Under"
    return {
        "kind": "total",
        "pick": f"{away} @ {home}: {label} {float(ct):g}",
        "side": side,
        "line": float(ct),
        "gap": gap,
        "signed_gap": inj_edge,
        "raw_signed_gap": raw_edge,
        "combo_injury_total": round(inj_for_gap, 2),
        "combo_model_weight": w,
    }


def _play_id(date_et: str, away: str, home: str) -> str:
    return f"combo_{date_et}_{away}@{home}"


def maybe_record_shadow_combo_for_scan(
    engine: Any,
    *,
    event_id: str | None,
    home: str,
    away: str,
    kickoff: Any,
    scan_at: str,
    snap: dict[str, Any],
    game_row: dict[str, Any] | None = None,
) -> None:
    if not SHADOW_COMBO_RECORD_ENABLED or not shadow_combo_enabled():
        return
    day = kickoff_date_et(kickoff)
    if day is None:
        return
    store = load_shadow_combo()
    date_et = day.isoformat()
    away_n, home_n = normalize_nba_team(away), normalize_nba_team(home)
    pid = _play_id(date_et, away_n, home_n)
    if any(p.get("id") == pid for p in store.get("plays") or []):
        return
    if any(p.get("id") == pid for p in store.get("pending") or []):
        return

    injury_snap = {
        "home_absences": snap.get("home_absences") or [],
        "away_absences": snap.get("away_absences") or [],
    }
    combo_snap = recompute_combo_projection(
        engine,
        home=home_n,
        away=away_n,
        kickoff=kickoff,
        lines=dict(snap.get("lines") or {}),
        injury_snap=injury_snap,
    )
    pick = combo_total_pick(combo_snap, home=home_n, away=away_n)
    if pick is None:
        return

    lines = dict(snap.get("lines") or {})
    tc = true_close_lines_for_game(game_row or {}) if game_row else None
    row = {
        "id": pid,
        "source": "shadow_combo",
        "event_id": str(event_id),
        "date_et": date_et,
        "kickoff": kickoff.isoformat() if hasattr(kickoff, "isoformat") else kickoff,
        "away": away_n,
        "home": home_n,
        "market": "total",
        "scan_at": scan_at,
        "pick": pick["pick"],
        "side": pick["side"],
        "line_lock": float(pick["line"]),
        "gap_pts": pick["gap"],
        "combo_raw_total": combo_snap.get("total"),
        "combo_injury_total": combo_snap.get("injury_total"),
        "combo_blended_total": pick.get("combo_injury_total"),
        "combo_model_weight": pick.get("combo_model_weight"),
        "close_total_true": (tc or {}).get("close_total_true"),
        "close_captured_at": (tc or {}).get("close_captured_at"),
        "consensus_total_at_scan": lines.get("consensus_total"),
        "result": None,
        "units": None,
    }
    store.setdefault("pending", []).append(row)
    save_shadow_combo(store)


def safe_maybe_record_shadow_combo_for_scan(*args: Any, **kwargs: Any) -> None:
    try:
        maybe_record_shadow_combo_for_scan(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pace shadow combo record skipped: %s", exc)


def _grade_total(act_total: int, *, close_total: float, side: str) -> str:
    diff = float(act_total) - float(close_total)
    if diff == 0:
        return "push"
    if side == "over":
        return "win" if diff > 0 else "loss"
    return "win" if diff < 0 else "loss"


def grade_shadow_combo_from_paper_store(paper_store: dict[str, Any] | None = None) -> int:
    from sharp_scout.nba.score_model.paper import load_paper_store

    paper = paper_store or load_paper_store()
    store = load_shadow_combo()
    pending = list(store.get("pending") or [])
    if not pending:
        return 0
    by_slot = {}
    for g in paper.get("games") or []:
        day = kickoff_date_et(g.get("kickoff"))
        if day is None:
            continue
        key = (day.isoformat(), normalize_nba_team(str(g.get("away"))), normalize_nba_team(str(g.get("home"))))
        by_slot[key] = g

    graded = 0
    still_pending: list[dict[str, Any]] = []
    for row in pending:
        key = (row.get("date_et"), row.get("away"), row.get("home"))
        g = by_slot.get(key)
        gr = (g or {}).get("graded")
        if not gr:
            still_pending.append(row)
            continue
        act = int(gr["actual_total"])
        lock = row.get("line_lock")
        if lock is None:
            still_pending.append(row)
            continue
        res = _grade_total(act, close_total=float(lock), side=str(row.get("side") or ""))
        row["result"] = res
        row["units"] = round(100.0 / 110.0, 4) if res == "win" else (-1.0 if res == "loss" else 0.0)
        row["actual_total"] = act
        row["graded_at"] = datetime.now(timezone.utc).isoformat()
        tc = true_close_lines_for_game(g) if g else None
        if tc:
            row["close_total_true"] = tc.get("close_total_true")
            row["close_captured_at"] = tc.get("close_captured_at")
        store.setdefault("plays", []).append(row)
        graded += 1

    store["pending"] = still_pending
    if graded:
        save_shadow_combo(store)
    return graded


def safe_grade_shadow_combo_from_paper_store(paper_store: dict[str, Any] | None = None) -> int:
    try:
        return grade_shadow_combo_from_paper_store(paper_store)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pace shadow combo grade skipped: %s", exc)
        return 0
