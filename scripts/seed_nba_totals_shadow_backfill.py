#!/usr/bin/env python3
"""Seed shadow ledger with Oct 25–28 backtest rows (source=backfill)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba.score_model.current_season_totals import project_total_current_season
from sharp_scout.nba.score_model.injury_adjust import apply_team_adjustments
from sharp_scout.nba.score_model.pace_v1 import injury_adj_pace_picks, pace_min_gap_pts
from sharp_scout.nba.score_model.paper import _merged_lines_from_scans, load_paper_store
from sharp_scout.nba.score_model.replay_engine import engine_at_start_of_et_date
from sharp_scout.nba.score_model.totals_shadow import (
    SHADOW_PATH,
    _grade_total,
    _units,
    append_backfill_plays,
    load_totals_shadow,
)
from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.utils.kickoff import parse_kickoff_utc

DAYS = [date(2026, 10, 25), date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)]


def _tip_snap(g: dict) -> dict:
    frozen = g.get("frozen") or {}
    scans = g.get("scans") or []
    if frozen.get("snapshot"):
        base = dict(frozen["snapshot"])
    elif scans:
        pre = [s for s in scans if not s.get("after_tip")] or scans
        base = dict(pre[-1])
    else:
        base = {}
    merged = _merged_lines_from_scans([s for s in scans if not s.get("after_tip")] or scans)
    if merged:
        base["lines"] = merged
    return base


def _shadow_pick(snap: dict, *, home: str, away: str) -> dict | None:
    picks = injury_adj_pace_picks(
        {
            "margin": 0.0,
            "total": snap["shadow_total"],
            "injury_margin": 0.0,
            "injury_total": snap["shadow_injury_total"],
            "lines": snap.get("lines") or {},
        },
        home=home,
        away=away,
        min_gap=pace_min_gap_pts(),
        require_raw_gap=True,
    )
    totals = [p for p in picks if p.get("kind") == "total"]
    if not totals:
        return None
    return max(totals, key=lambda x: float(x.get("gap") or 0))


def main() -> int:
    store = load_paper_store()
    rows: list[dict] = []
    for day in DAYS:
        engine = engine_at_start_of_et_date(day, paper_store=store, use_espn=True)
        for g in store.get("games") or []:
            if kickoff_date_et(g.get("kickoff")) != day:
                continue
            gr = g.get("graded")
            if not gr:
                continue
            home, away = str(g.get("home")), str(g.get("away"))
            snap = _tip_snap(g)
            lines = snap.get("lines") or {}
            ct = lines.get("consensus_total")
            if ct is None:
                continue
            kick = parse_kickoff_utc(g.get("kickoff"))
            if kick is None:
                continue
            cs = project_total_current_season(engine, home, away, game_date=kick)
            _h, _a, _m, inj_t = apply_team_adjustments(
                float(cs["total_home_pts"]),
                float(cs["total_away_pts"]),
                home_abs=snap.get("home_absences") or [],
                away_abs=snap.get("away_absences") or [],
            )
            shadow_snap = {
                "shadow_total": float(cs["total"]),
                "shadow_injury_total": round(inj_t, 2),
                "lines": lines,
            }
            pick = _shadow_pick(shadow_snap, home=home, away=away)
            if not pick:
                continue
            act_total = int(gr["actual_total"])
            act_margin = int(gr["actual_margin"])
            away_score = (act_total - act_margin) // 2
            home_score = (act_total + act_margin) // 2
            side = str(pick.get("side") or "")
            res = _grade_total(act_total, close_total=float(ct), side=side)
            if res not in ("win", "loss", "push"):
                continue
            rows.append(
                {
                    "id": f"cs-shadow-backfill-{g.get('event_id', '')}-total",
                    "date_et": day.isoformat(),
                    "kickoff": g.get("kickoff"),
                    "away": away,
                    "home": home,
                    "market": "total",
                    "pick": pick.get("pick"),
                    "side": side,
                    "line": pick.get("line"),
                    "gap_pts": round(float(pick.get("gap") or 0), 2),
                    "shadow_total": shadow_snap["shadow_total"],
                    "shadow_injury_total": shadow_snap["shadow_injury_total"],
                    "live_total": float(snap.get("total") or 0),
                    "live_injury_total": snap.get("injury_total"),
                    "diagnostics": cs.get("total_diagnostics") or {},
                    "result": res,
                    "units": _units(res),
                    "espn_away_score": away_score,
                    "espn_home_score": home_score,
                    "backfill_note": "Oct 2026 slate replay at tip (2026-27 totals method)",
                }
            )
    n = append_backfill_plays(rows)
    summ = load_totals_shadow()
    print(f"Backfill added {n} rows → {SHADOW_PATH} ({len(summ.get('plays') or [])} plays total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
