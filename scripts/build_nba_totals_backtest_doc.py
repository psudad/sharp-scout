#!/usr/bin/env python3
"""Write docs/nba_totals_current_season.md — old vs new totals on Oct 2026 slates."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba.score_model.current_season_totals import project_total_legacy_prior_blend
from sharp_scout.nba.score_model.pace_v1 import injury_adj_pace_picks, pace_min_gap_pts
from sharp_scout.nba.score_model.paper import _merged_lines_from_scans, load_paper_store
from sharp_scout.nba.score_model.replay_engine import engine_at_start_of_et_date
from sharp_scout.nba.score_model.replay_project import recompute_v1_tip_snapshot
from sharp_scout.nba.slate_et import kickoff_date_et

OUT = ROOT / "docs" / "nba_totals_current_season.md"
DAYS = [date(2026, 10, 25), date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)]
MIN_GAP = 3.0


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


def _qualify_total(snap: dict, *, home: str, away: str) -> dict | None:
    picks = injury_adj_pace_picks(snap, home=home, away=away, min_gap=pace_min_gap_pts())
    totals = [p for p in picks if p.get("kind") == "total"]
    if not totals:
        return None
    return max(totals, key=lambda x: float(x.get("gap") or 0))


def main() -> int:
    store = load_paper_store()
    lines_out: list[str] = [
        "# NBA Pace totals — current-season method backtest",
        "",
        "Compares **legacy** totals (prior-blended pace/ORTG from committed priors + history) "
        "vs **2026-27 only** game-log averages (this PR). Injury-adj totals use the same "
        "ESPN absence rules; spreads unchanged.",
        "",
        f"Min gap for play flag: **{MIN_GAP} pt** raw + injury rules (v1).",
        "",
    ]
    for day in DAYS:
        engine = engine_at_start_of_et_date(day, paper_store=store, use_espn=True)
        lines_out.append(f"## {day.isoformat()} (ET slate)")
        lines_out.append("")
        lines_out.append(
            "| Game | Line | Actual | Old total | New total | Old inj total | New inj total | "
            "Old gap | New gap | v1 play (new) | Result |"
        )
        lines_out.append("|------|------|--------|-----------|-----------|---------------|"
                         "---------------|---------|---------|---------------|--------|")
        for g in store.get("games") or []:
            if kickoff_date_et(g.get("kickoff")) != day:
                continue
            home, away = str(g.get("home")), str(g.get("away"))
            gr = g.get("graded")
            if not gr:
                continue
            snap = _tip_snap(g)
            ct = (snap.get("lines") or {}).get("consensus_total")
            if ct is None:
                continue
            act = int(gr["actual_total"])
            kick = g.get("kickoff")
            old_t = project_total_legacy_prior_blend(engine, home, away, game_date=kick)
            new_snap = recompute_v1_tip_snapshot(
                engine,
                home=home,
                away=away,
                kickoff=kick,
                lines=snap.get("lines") or {},
                injury_snap={
                    "home_absences": snap.get("home_absences") or [],
                    "away_absences": snap.get("away_absences") or [],
                },
            )
            new_t = float(new_snap["total"])
            old_inj = float(snap.get("injury_total") or old_t)
            new_inj = float(new_snap["injury_total"])
            old_gap = old_inj - float(ct)
            new_gap = new_inj - float(ct)
            pick = _qualify_total(new_snap, home=home, away=away)
            play_s = pick.get("pick", "—") if pick else "—"
            res = "—"
            if pick:
                side = pick.get("side")
                if side == "over":
                    res = "W" if act > float(ct) else ("P" if act == float(ct) else "L")
                elif side == "under":
                    res = "W" if act < float(ct) else ("P" if act == float(ct) else "L")
            lines_out.append(
                f"| {away} @ {home} | {float(ct):g} | {act} | {old_t:.1f} | {new_t:.1f} | "
                f"{old_inj:.1f} | {new_inj:.1f} | {old_gap:+.1f} | {new_gap:+.1f} | {play_s} | {res} |"
            )
        lines_out.append("")

    lines_out.extend(
        [
            "## Oct 27–28 headline totals (official card games)",
            "",
            "Honest read on whether the **new** method still flags the Oct 28 losses:",
            "",
            "- **DEN @ NOP Over 240.5** — check New gap column above; if still ≥ 3, the play would still publish.",
            "- **LAL @ LAC Over 224.5** — same.",
            "- **NYK @ CHI Under** — compare old vs new under gap.",
            "- **GSW @ MIN Over 227.5** — winner either way if gap stays ≥ 3.",
            "",
            "_Generated by `scripts/build_nba_totals_backtest_doc.py`._",
            "",
        ]
    )
    OUT.write_text("\n".join(lines_out) + "\n")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
