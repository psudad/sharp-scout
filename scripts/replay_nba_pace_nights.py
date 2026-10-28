#!/usr/bin/env python3
"""Replay Oct 25–27: v1 mechanical (3 pt) vs official Jason card vs v2 shadow."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR
from sharp_scout.nba.score_model.official_pace import load_official_pace
from sharp_scout.nba.score_model.pace_v1 import pace_display_pick_from_snapshot as v1_pick
from sharp_scout.nba.score_model.pace_v2_qualify import evaluate_pace_pick_v2
from sharp_scout.nba.score_model.paper import _grade_ats_margin, _grade_ou, _merged_lines_from_scans
from sharp_scout.nba.score_model.pace_clv import last_pre_tip_scan, pace_clv_fields
from sharp_scout.nba.score_model.replay_engine import engine_at_start_of_et_date, shadow_engine_at_start_of_et_date
from sharp_scout.nba.score_model.replay_project import recompute_v1_tip_snapshot, recompute_v2_tip_snapshot
from sharp_scout.nba.slate_et import kickoff_date_et


def _official_index() -> dict[tuple[str, str, str], dict]:
    out: dict[tuple[str, str, str], dict] = {}
    for p in load_official_pace().get("plays") or []:
        out[(str(p.get("date_et")), str(p.get("away")), str(p.get("home")))] = p
    return out


def _tip_src(g: dict) -> dict:
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
    for s in reversed(scans):
        if s.get("home_absences") or s.get("away_absences"):
            base["home_absences"] = s.get("home_absences") or []
            base["away_absences"] = s.get("away_absences") or []
            break
    return base


def _grade(pick: dict, gr: dict, snap: dict) -> str | None:
    cs, ct = gr.get("close_spread_home"), gr.get("close_total")
    if pick["kind"] == "spread" and cs is not None:
        pm = float(snap.get("injury_margin") or snap.get("margin") or 0)
        return _grade_ats_margin(int(gr["actual_margin"]), cs, min_edge=0.0, proj_margin=pm)
    if pick["kind"] == "total" and ct is not None:
        pt = float(snap.get("injury_total") or snap.get("total") or 0)
        return _grade_ou(int(gr["actual_total"]), ct, min_edge=0.0, proj_total=pt)
    return None


def replay_day(store: dict, day: date, *, official: dict, use_espn: bool = True) -> list[dict]:
    v1_engine = engine_at_start_of_et_date(day, paper_store=store, use_espn=use_espn)
    v2_engine = shadow_engine_at_start_of_et_date(day, paper_store=store, use_espn=use_espn)
    rows: list[dict] = []
    for g in store.get("games") or []:
        if kickoff_date_et(g.get("kickoff")) != day:
            continue
        home, away = str(g.get("home")), str(g.get("away"))
        if not (g.get("scans") or g.get("frozen")):
            continue
        tip = _tip_src(g)
        lines = dict(tip.get("lines") or {})
        inj = {"home_absences": tip.get("home_absences") or [], "away_absences": tip.get("away_absences") or []}
        v1_snap = recompute_v1_tip_snapshot(
            v1_engine, home=home, away=away, kickoff=g.get("kickoff"), lines=lines, injury_snap=inj
        )
        v2_snap = recompute_v2_tip_snapshot(
            v2_engine, home=home, away=away, kickoff=g.get("kickoff"), lines=lines, injury_snap=inj
        )
        mech = v1_pick(v1_snap, home=home, away=away)
        v2_pick, v2_meta = evaluate_pace_pick_v2(v2_snap, home=home, away=away, engine=v2_engine)
        off = official.get((day.isoformat(), away, home))
        row = {
            "matchup": f"{away} @ {home}",
            "official_pick": (off or {}).get("pick"),
            "mechanical_v1_pick": (mech or {}).get("pick"),
            "mechanical_v1_gap": (mech or {}).get("gap"),
            "v2_shadow_pick": (v2_pick or {}).get("pick") if v2_pick else (v2_meta or {}).get("would_be_pick", {}).get("pick"),
            "v2_shadow_gap": (v2_pick or {}).get("gap") if v2_pick else (v2_meta or {}).get("would_be_pick", {}).get("gap"),
            "v2_note": (v2_meta or {}).get("exclusion_note"),
        }
        gr = g.get("graded")
        pre = last_pre_tip_scan(g.get("scans") or [], kickoff=g.get("kickoff"))
        if gr and mech and pre:
            row["mech_result"] = _grade(mech, gr, v1_snap)
            row["mech_clv"] = pace_clv_fields(
                pick=mech,
                pre_tip=pre,
                close_spread_home=gr.get("close_spread_home"),
                close_total=gr.get("close_total"),
                proj_margin=float(v1_snap.get("injury_margin") or 0),
                proj_total=float(v1_snap.get("injury_total") or 0),
            ).get("clv_toward_model")
        if gr and v2_pick and pre:
            row["v2_result"] = _grade(v2_pick, gr, v2_snap)
        if off and gr:
            row["official_result"] = off.get("result")
        rows.append(row)
    return rows


def _rec(rows: list[dict], pick_key: str, res_key: str) -> str:
    w = l = 0
    for r in rows:
        if not r.get(pick_key):
            continue
        res = r.get(res_key)
        if res == "win":
            w += 1
        elif res == "loss":
            l += 1
    return f"{w}-{l}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", default="2026-10-25,2026-10-26,2026-10-27")
    parser.add_argument("--paper", type=Path, default=DATA_DIR / "paper" / "nba_score_model.json")
    parser.add_argument("--no-espn", action="store_true")
    args = parser.parse_args()
    store = json.loads(args.paper.read_text())
    official = _official_index()
    days = [date.fromisoformat(x.strip()) for x in args.dates.split(",") if x.strip()]
    all_rows: list[dict] = []
    print("NBA Pace replay — v1 mechanical (3 pt) vs official card vs v2 shadow\n")
    for d in days:
        day_rows = replay_day(store, d, official=official, use_espn=not args.no_espn)
        all_rows.extend(day_rows)
        print(f"=== {d.isoformat()} (ET) ===")
        for r in day_rows:
            print(
                f"  {r['matchup']}: official {r.get('official_pick') or '—'} | "
                f"v1 mech {r.get('mechanical_v1_pick') or '—'} (gap {r.get('mechanical_v1_gap')}) | "
                f"v2 {r.get('v2_shadow_pick') or '—'} (gap {r.get('v2_shadow_gap')})"
            )
            if r.get("v2_note"):
                print(f"    v2: {r['v2_note']}")
        print()
    day_set = {d.isoformat() for d in days}
    all_off = [p for p in load_official_pace()["plays"] if p.get("date_et") in day_set]
    jason = [p for p in all_off if p.get("source") == "official_backfill"]
    ow = sum(1 for p in jason if p.get("result") == "win")
    ol = sum(1 for p in jason if p.get("result") == "loss")
    print("=== Record Oct 25–27 ===")
    print(f"  Official Jason card (manual backfill Oct 25–26): {ow}-{ol} ({len(jason)} plays)")
    if len(all_off) > len(jason):
        aw = sum(1 for p in all_off if p.get("result") == "win")
        al = sum(1 for p in all_off if p.get("result") == "loss")
        print(f"  Full official ledger incl. auto Oct 27+: {aw}-{al} ({len(all_off)} plays)")
    print(f"  v1 mechanical (3 pt, replay): {_rec(all_rows, 'mechanical_v1_pick', 'mech_result')}")
    print(f"  v2 shadow (replay): {_rec(all_rows, 'v2_shadow_pick', 'v2_result')}")
    clv_hits = [r["mech_clv"] for r in all_rows if r.get("mech_clv") is not None]
    if clv_hits:
        print(f"  v1 mechanical CLV toward model: {sum(1 for x in clv_hits if x)}/{len(clv_hits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
