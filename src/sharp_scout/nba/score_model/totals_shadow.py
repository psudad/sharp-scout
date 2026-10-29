"""Shadow ledger: 2026-27-only totals (tracking — does not affect live Pace card)."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.nba.score_model.current_season_totals import project_total_current_season
from sharp_scout.nba.score_model.injury_adjust import apply_team_adjustments
from sharp_scout.nba.score_model.pace_v1 import injury_adj_pace_picks, pace_min_gap_pts
from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

# Tests may set False or monkeypatch `maybe_record_totals_shadow_for_scan`.
SHADOW_RECORD_ENABLED = True

SHADOW_PATH = DATA_DIR / "paper" / "nba_totals_current_season_shadow.json"
SHADOW_CSV_PATH = DATA_DIR / "paper" / "nba_totals_current_season_shadow.csv"


def _empty() -> dict[str, Any]:
    return {
        "version": 1,
        "notes": "2026-27 game-log totals experiment (shadow). Not official Pace plays.",
        "plays": [],
        "pending": [],
        "updated_at": None,
    }


def load_totals_shadow(path: Path | None = None) -> dict[str, Any]:
    p = path or SHADOW_PATH
    if not p.exists():
        return _empty()
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return _empty()
    raw.setdefault("plays", [])
    raw.setdefault("pending", [])
    return raw


def save_totals_shadow(store: dict[str, Any], path: Path | None = None) -> None:
    p = path or SHADOW_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")
    _write_csv(store)


def _write_csv(store: dict[str, Any]) -> None:
    fields = [
        "id",
        "source",
        "date_et",
        "kickoff",
        "away",
        "home",
        "market",
        "pick",
        "line",
        "gap_pts",
        "shadow_total",
        "shadow_injury_total",
        "live_total",
        "live_injury_total",
        "result",
        "units",
        "espn_away_score",
        "espn_home_score",
    ]
    with SHADOW_CSV_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in store.get("plays") or []:
            w.writerow({k: r.get(k) for k in fields})


def _slot_key(date_et: str, away: str, home: str) -> tuple[str, str, str]:
    return (date_et, normalize_nba_team(away), normalize_nba_team(home))


def summarize_totals_shadow(store: dict[str, Any] | None = None) -> dict[str, Any]:
    store = store or load_totals_shadow()
    plays = [p for p in store.get("plays") or [] if p.get("result") in ("win", "loss", "push")]
    w = sum(1 for p in plays if p.get("result") == "win")
    l = sum(1 for p in plays if p.get("result") == "loss")
    pu = sum(1 for p in plays if p.get("result") == "push")
    units = round(w * (100.0 / 110.0) - l * 1.0, 2)
    denom = w + l
    return {
        "record": f"{w}-{l}" + (f"-{pu}" if pu else ""),
        "wins": w,
        "losses": l,
        "pushes": pu,
        "units": units,
        "win_pct": f"{100.0 * w / denom:.1f}%" if denom else "—",
        "n_plays": len(plays),
    }


def _shadow_injury_total(
    cs: dict[str, Any],
    *,
    home_abs: list[dict[str, Any]],
    away_abs: list[dict[str, Any]],
) -> float:
    _h, _a, _m, total = apply_team_adjustments(
        float(cs["total_home_pts"]),
        float(cs["total_away_pts"]),
        home_abs=home_abs,
        away_abs=away_abs,
    )
    return round(total, 2)


def _shadow_total_pick(
    *,
    home: str,
    away: str,
    lines: dict[str, Any],
    raw_total: float,
    injury_total: float,
) -> dict[str, Any] | None:
    ct = lines.get("consensus_total")
    if ct is None:
        return None
    snap = {
        "margin": 0.0,
        "total": raw_total,
        "injury_margin": 0.0,
        "injury_total": injury_total,
        "lines": lines,
    }
    picks = injury_adj_pace_picks(
        snap, home=home, away=away, min_gap=pace_min_gap_pts(), require_raw_gap=True
    )
    totals = [p for p in picks if p.get("kind") == "total"]
    if not totals:
        return None
    return max(totals, key=lambda x: float(x.get("gap") or 0))


def compute_shadow_totals_sidecar(
    engine: Any,
    *,
    home: str,
    away: str,
    kickoff: datetime,
    lines: dict[str, Any],
    live_total: float,
    live_injury_total: float | None,
    home_absences: list[dict[str, Any]] | None = None,
    away_absences: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pure shadow math — never mutates live projection fields."""
    cs = project_total_current_season(engine, home, away, game_date=kickoff)
    inj_t = _shadow_injury_total(
        cs,
        home_abs=home_absences or [],
        away_abs=away_absences or [],
    )
    pick = _shadow_total_pick(
        home=home,
        away=away,
        lines=lines,
        raw_total=float(cs["total"]),
        injury_total=inj_t,
    )
    return {
        "shadow_total": float(cs["total"]),
        "shadow_injury_total": inj_t,
        "shadow_diagnostics": cs.get("total_diagnostics") or {},
        "shadow_total_pick": pick,
        "live_total": live_total,
        "live_injury_total": live_injury_total,
    }


def maybe_record_totals_shadow_for_scan(
    engine: Any,
    *,
    event_id: str | None,
    home: str,
    away: str,
    kickoff: Any,
    scan_at: str,
    snap: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> None:
    """Side effect only: shadow ledger + log line. Does not mutate ``snap``."""
    if not SHADOW_RECORD_ENABLED:
        return
    from sharp_scout.utils.kickoff import parse_kickoff_utc

    kick_dt = parse_kickoff_utc(kickoff)
    if kick_dt is None:
        return
    lines = snap.get("lines") or {}
    live_inj = snap.get("injury_total")
    sidecar = compute_shadow_totals_sidecar(
        engine,
        home=home,
        away=away,
        kickoff=kick_dt,
        lines=lines,
        live_total=float(snap.get("total") or 0),
        live_injury_total=float(live_inj) if live_inj is not None else None,
        home_absences=snap.get("home_absences") or [],
        away_absences=snap.get("away_absences") or [],
    )
    pick = sidecar.get("shadow_total_pick")
    pick_s = (pick or {}).get("pick") if pick else "—"
    logger.info(
        "NBA totals shadow (tracking): %s @ %s live_total=%s shadow_total=%s would_be=%s",
        away,
        home,
        sidecar.get("live_total"),
        sidecar.get("shadow_total"),
        pick_s,
    )
    record_shadow_scan(
        event_id=event_id,
        home=home,
        away=away,
        kickoff=kick_dt,
        scan_at=scan_at,
        sidecar=sidecar,
        store=store,
    )


def safe_maybe_record_totals_shadow_for_scan(
    engine: Any,
    *,
    event_id: str | None,
    home: str,
    away: str,
    kickoff: Any,
    scan_at: str,
    snap: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> None:
    """Never raises — live scans must continue if shadow logging fails."""
    try:
        maybe_record_totals_shadow_for_scan(
            engine,
            event_id=event_id,
            home=home,
            away=away,
            kickoff=kickoff,
            scan_at=scan_at,
            snap=snap,
            store=store,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("NBA totals shadow record skipped: %s", exc)


def safe_grade_shadow_from_paper_store(paper_store: dict[str, Any] | None = None) -> int:
    """Never raises — settlement must not depend on shadow grading."""
    try:
        return grade_shadow_from_paper_store(paper_store)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NBA totals shadow grade skipped: %s", exc)
        return 0


def record_shadow_scan(
    *,
    event_id: str | None,
    home: str,
    away: str,
    kickoff: Any,
    scan_at: str,
    sidecar: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> None:
    """Update pending shadow row for this matchup (latest scan wins)."""
    store = store or load_totals_shadow()
    day = kickoff_date_et(kickoff)
    if day is None:
        return
    date_et = day.isoformat()
    pick = sidecar.get("shadow_total_pick")
    entry = {
        "event_id": event_id,
        "date_et": date_et,
        "kickoff": kickoff,
        "away": away,
        "home": home,
        "scan_at": scan_at,
        "shadow_total": sidecar.get("shadow_total"),
        "shadow_injury_total": sidecar.get("shadow_injury_total"),
        "live_total": sidecar.get("live_total"),
        "live_injury_total": sidecar.get("live_injury_total"),
        "shadow_diagnostics": sidecar.get("shadow_diagnostics") or {},
        "would_play": pick,
        "line": (pick or {}).get("line") if pick else None,
    }
    slot = _slot_key(date_et, away, home)
    pending = [p for p in store.get("pending") or [] if _slot_key(str(p.get("date_et")), str(p.get("away")), str(p.get("home"))) != slot]
    pending.append(entry)
    store["pending"] = pending
    save_totals_shadow(store)


def _grade_total(act_total: int, *, close_total: float, side: str) -> str:
    diff = float(act_total) - float(close_total)
    if abs(diff) < 0.01:
        return "push"
    if side == "over":
        return "win" if diff > 0 else "loss"
    return "win" if diff < 0 else "loss"


def _units(result: str) -> float:
    if result == "win":
        return round(100.0 / 110.0, 2)
    if result == "loss":
        return -1.0
    return 0.0


def grade_shadow_from_paper_store(paper_store: dict[str, Any] | None = None) -> int:
    """Grade shadow total plays from tip pending snapshot (last pre-tip would_play)."""
    from sharp_scout.nba.score_model.paper import _game_excluded

    paper_store = paper_store or {}
    shadow = load_totals_shadow()
    added = 0
    play_keys = {
        _slot_key(str(p.get("date_et")), str(p.get("away")), str(p.get("home")))
        for p in shadow.get("plays") or []
    }
    pending_by_slot = {
        _slot_key(str(p.get("date_et")), str(p.get("away")), str(p.get("home"))): p
        for p in shadow.get("pending") or []
    }

    for g in paper_store.get("games") or []:
        if _game_excluded(g) or not g.get("graded"):
            continue
        home, away = str(g.get("home") or ""), str(g.get("away") or "")
        day = kickoff_date_et(g.get("kickoff"))
        if day is None:
            continue
        slot = _slot_key(day.isoformat(), away, home)
        if slot in play_keys:
            continue
        pending = pending_by_slot.get(slot)
        if not pending:
            continue
        pick = pending.get("would_play")
        if not pick:
            continue
        gr = g["graded"]
        ct = gr.get("close_total")
        if ct is None:
            continue
        act_total = int(gr["actual_total"])
        act_margin = int(gr["actual_margin"])
        home_score = (act_total + act_margin) // 2
        away_score = (act_total - act_margin) // 2
        side = str(pick.get("side") or "")
        res = _grade_total(act_total, close_total=float(ct), side=side)
        if res not in ("win", "loss", "push"):
            continue
        entry = {
            "id": f"cs-shadow-{g.get('event_id', '')}-total",
            "source": "scan",
            "date_et": day.isoformat(),
            "kickoff": g.get("kickoff"),
            "away": away,
            "home": home,
            "market": "total",
            "pick": pick.get("pick"),
            "side": side,
            "line": pick.get("line"),
            "gap_pts": round(float(pick.get("gap") or 0), 2),
            "shadow_total": pending.get("shadow_total"),
            "shadow_injury_total": pending.get("shadow_injury_total"),
            "live_total": pending.get("live_total"),
            "live_injury_total": pending.get("live_injury_total"),
            "diagnostics": pending.get("shadow_diagnostics") or {},
            "result": res,
            "units": _units(res),
            "espn_away_score": away_score,
            "espn_home_score": home_score,
            "graded_at": datetime.now(timezone.utc).isoformat(),
        }
        shadow.setdefault("plays", []).append(entry)
        play_keys.add(slot)
        added += 1

    if added:
        save_totals_shadow(shadow)
    return added


def append_backfill_plays(rows: list[dict[str, Any]], *, store: dict[str, Any] | None = None) -> int:
    store = store or load_totals_shadow()
    existing = {
        _slot_key(str(p.get("date_et")), str(p.get("away")), str(p.get("home")))
        for p in store.get("plays") or []
    }
    added = 0
    for row in rows:
        slot = _slot_key(str(row.get("date_et")), str(row.get("away")), str(row.get("home")))
        if slot in existing:
            continue
        row = {**row, "source": "backfill"}
        store.setdefault("plays", []).append(row)
        existing.add(slot)
        added += 1
    if added:
        save_totals_shadow(store)
    return added
