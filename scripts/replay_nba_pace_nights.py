#!/usr/bin/env python3
"""Replay Pace of Play picks using historical engine + stored lines/injuries (no Odds API)."""

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
from sharp_scout.nba.score_model.pace_qualify import evaluate_pace_pick, pace_min_gap_pts
from sharp_scout.nba.score_model.paper import _grade_ats_margin, _grade_ou, _merged_lines_from_scans
from sharp_scout.nba.score_model.replay_engine import engine_at_start_of_et_date
from sharp_scout.nba.score_model.replay_project import recompute_tip_snapshot
from sharp_scout.nba.slate_et import kickoff_date_et


def _official_index() -> dict[tuple[str, str, str], dict]:
    store = load_official_pace()
    out: dict[tuple[str, str, str], dict] = {}
    for p in store.get("plays") or []:
        key = (
            str(p.get("date_et") or ""),
            str(p.get("away") or ""),
            str(p.get("home") or ""),
        )
        out[key] = p
    return out


def _best_tip_scan(g: dict) -> dict:
    scans = g.get("scans") or []
    frozen = g.get("frozen") or {}
    if frozen.get("snapshot"):
        base = dict(frozen["snapshot"])
    elif scans:
        base = dict(scans[-1])
    else:
        base = {}
    merged = _merged_lines_from_scans(scans)
    if merged:
        base["lines"] = merged
    for s in reversed(scans):
        if s.get("home_absences") or s.get("away_absences"):
            base["home_absences"] = s.get("home_absences") or []
            base["away_absences"] = s.get("away_absences") or []
            if s.get("injury_margin") is not None:
                base["injury_margin"] = s.get("injury_margin")
            if s.get("margin") is not None and base.get("margin") is None:
                base["margin"] = s.get("margin")
            break
    return base


def _tip_injury_snap(_g: dict, snap: dict) -> dict:
    return {
        "home_absences": snap.get("home_absences") or [],
        "away_absences": snap.get("away_absences") or [],
    }


def _grade_pick(pick: dict, gr: dict, fresh: dict) -> str | None:
    cs, ct = gr.get("close_spread_home"), gr.get("close_total")
    act_m = int(gr["actual_margin"])
    act_t = int(gr["actual_total"])
    min_gap = 0.0
    if pick["kind"] == "spread" and cs is not None:
        pm = float(fresh.get("injury_margin") or fresh.get("margin") or 0)
        return _grade_ats_margin(act_m, cs, min_edge=min_gap, proj_margin=pm)
    if pick["kind"] == "total" and ct is not None:
        pt = float(fresh.get("injury_total") or fresh.get("total") or 0)
        return _grade_ou(act_t, ct, min_edge=min_gap, proj_total=pt)
    return None


def replay_day(
    store: dict,
    day: date,
    *,
    official: dict[tuple[str, str, str], dict],
    use_espn: bool = True,
) -> tuple[list[dict], dict[str, float]]:
    engine = engine_at_start_of_et_date(day, paper_store=store, use_espn=use_espn)
    rows: list[dict] = []
    for g in store.get("games") or []:
        if kickoff_date_et(g.get("kickoff")) != day:
            continue
        home, away = str(g.get("home")), str(g.get("away"))
        scans = g.get("scans") or []
        if not scans:
            continue
        tip_src = _best_tip_scan(g)
        merged = dict(tip_src.get("lines") or {})

        stored_margin = tip_src.get("margin")
        stored_inj = tip_src.get("injury_margin")

        fresh = recompute_tip_snapshot(
            engine,
            home=home,
            away=away,
            kickoff=g.get("kickoff"),
            lines=merged,
            injury_snap=_tip_injury_snap(g, tip_src),
        )

        pick_new, meta = evaluate_pace_pick(fresh, home=home, away=away, engine=engine)

        off = official.get((day.isoformat(), away, home))
        old_pick = off.get("pick") if off else None
        old_gap = off.get("gap_pts") if off else None

        row: dict = {
            "date_et": day.isoformat(),
            "matchup": f"{away} @ {home}",
            "official_card_pick": old_pick,
            "official_gap": old_gap,
            "replay_pick": (pick_new or {}).get("pick") if pick_new else None,
            "replay_gap": (pick_new or {}).get("gap") if pick_new else None,
            "stored_margin": stored_margin,
            "stored_injury_margin": stored_inj,
            "recomputed_margin": fresh.get("margin"),
            "recomputed_injury_margin": fresh.get("injury_margin"),
            "large_gap_warning": (pick_new or {}).get("large_gap_warning")
            or ((meta or {}).get("would_be_pick") or {}).get("large_gap_warning"),
            "exclusion_note": (meta or {}).get("exclusion_note"),
            "would_be_pick": ((meta or {}).get("would_be_pick") or {}).get("pick"),
            "would_be_gap": ((meta or {}).get("would_be_pick") or {}).get("gap"),
        }
        gr = g.get("graded")
        if gr and pick_new:
            row["replay_result"] = _grade_pick(pick_new, gr, fresh)
        if off:
            row["official_result"] = off.get("result")
        rows.append(row)
    rows.sort(key=lambda r: r["matchup"])
    return rows, {}


def _record(plays: list[dict], *, pick_key: str, result_key: str) -> dict:
    w = l = 0
    units = 0.0
    for p in plays:
        if not p.get(pick_key):
            continue
        res = p.get(result_key)
        if res == "win":
            w += 1
            units += 100.0 / 110.0
        elif res == "loss":
            l += 1
            units -= 1.0
    return {"wins": w, "losses": l, "record": f"{w}-{l}", "units": round(units, 2)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dates",
        default="2026-10-25,2026-10-26,2026-10-27",
        help="Comma-separated ET dates",
    )
    parser.add_argument(
        "--paper",
        type=Path,
        default=DATA_DIR / "paper" / "nba_score_model.json",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-espn", action="store_true", help="Paper-graded finals only (faster/offline)")
    args = parser.parse_args()
    store = json.loads(args.paper.read_text())
    official = _official_index()
    days = [date.fromisoformat(x.strip()) for x in args.dates.split(",") if x.strip()]
    report: dict[str, list[dict]] = {}
    all_rows: list[dict] = []
    for d in days:
        day_rows, _dbg = replay_day(
            store, d, official=official, use_espn=not args.no_espn
        )
        report[d.isoformat()] = day_rows
        all_rows.extend(day_rows)

    day_set = {d.isoformat() for d in days}
    off_ledger = [
        p
        for p in load_official_pace().get("plays") or []
        if str(p.get("date_et") or "") in day_set
    ]
    off_w = sum(1 for p in off_ledger if p.get("result") == "win")
    off_l = sum(1 for p in off_ledger if p.get("result") == "loss")
    off_units = sum(float(p.get("units") or 0) for p in off_ledger)

    new_plays = [r for r in all_rows if r.get("replay_pick")]

    summary = {
        "official_card": {
            "wins": off_w,
            "losses": off_l,
            "record": f"{off_w}-{off_l}",
            "units": round(off_units, 2),
            "n_plays": len(off_ledger),
        },
        "replay_rules": _record(new_plays, pick_key="replay_pick", result_key="replay_result"),
    }

    if args.json:
        print(json.dumps({"days": report, "summary": summary}, indent=2))
        return 0

    print("NBA Pace replay — recomputed engine + stored lines/injuries\n")
    for d in days:
        print(f"=== {d.isoformat()} (ET) ===")
        for row in report[d.isoformat()]:
            old = row["official_card_pick"] or "—"
            new = row["replay_pick"] or "—"
            ex = row.get("exclusion_note")
            ch = ""
            if row["official_card_pick"] and row.get("replay_pick") != row["official_card_pick"]:
                ch = " (changed)"
            elif row.get("would_be_pick") and not row.get("replay_pick"):
                ch = " (excluded)"
            elif row["official_card_pick"] and not row.get("replay_pick"):
                ch = " (no play)"
            gap_s = row.get("replay_gap")
            if gap_s is None:
                gap_s = row.get("would_be_gap")
            print(
                f"  {row['matchup']}: official {old} → replay {new} "
                f"[recomputed inj margin {row.get('recomputed_injury_margin')} vs stored {row.get('stored_injury_margin')}; "
                f"gap {gap_s}]{ch}"
            )
            if row.get("would_be_pick") and not row.get("replay_pick"):
                print(f"    Would-be: {row['would_be_pick']} (gap {row.get('would_be_gap')})")
            if ex:
                print(f"    Note: {ex}")
        print()

    print("=== Record Oct 25–27 (games with a pick) ===")
    print(f"  Official card: {summary['official_card']['record']} ({summary['official_card']['units']:+.2f}u)")
    print(f"  Replay rules:  {summary['replay_rules']['record']} ({summary['replay_rules']['units']:+.2f}u)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
