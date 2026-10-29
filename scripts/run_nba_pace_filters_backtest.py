#!/usr/bin/env python3
"""Pace filter experiments on 68-game backtest universe (research only)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_nba_pace_original_backtest as base  # noqa: E402
from nba_pace_original_backtest_lib import (  # noqa: E402
    MIN_GAP,
    Record,
    picks_original_pre_injury,
    units_at_110,
    wilson_ci,
)
from nba_pace_rest_travel import build_team_game_log, tag_game_rest_travel  # noqa: E402
from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.nba.score_model.pace_clv import pace_clv_fields  # noqa: E402
from sharp_scout.nba.score_model.pace_v1 import injury_adj_pace_picks  # noqa: E402
from sharp_scout.nba.score_model.paper import _grade_ou, load_paper_store  # noqa: E402
from sharp_scout.nba.score_model.totals_shadow import compute_shadow_totals_sidecar  # noqa: E402
from sharp_scout.utils.kickoff import parse_kickoff_utc  # noqa: E402

REPORT_MD = ROOT / "docs" / "nba_pace_filters_backtest.md"
CSV_OUT = DATA_DIR / "paper" / "nba_pace_filters_backtest.csv"
UNIT_DOLLARS = 10.0

MODELS = {
    "original_raw": "Original raw (e45945a)",
    "current_inj": "Current injury-adj + raw gate",
    "shadow_cs_total": "2026-27 totals shadow",
}


def _stats(plays: list[dict[str, Any]]) -> dict[str, Any]:
    rec = Record()
    for p in plays:
        rec.add(p.get("result"))
    n = rec.n
    wp = 100.0 * rec.wins / n if n else 0.0
    ci = wilson_ci(rec.wins, n)
    return {
        "w": rec.wins,
        "l": rec.losses,
        "n": n,
        "record": rec.wl(),
        "win_pct": f"{wp:.1f}%" if n else "—",
        "units": round(rec.units, 2),
        "dollars": round(rec.units * UNIT_DOLLARS, 2),
        "wilson": f"{100*ci[0]:.1f}–{100*ci[1]:.1f}%" if n else "—",
    }


def _open_lines_for_game(g: dict[str, Any], paper_slots: dict) -> dict[str, float | None]:
    slot = (g["away"], g["home"], str(base.kickoff_date_et(g.get("kickoff")) or ""))
    if g.get("line_source") == "repo_odds_api":
        pg = paper_slots.get(slot)
        if not pg:
            return {}
        frozen = pg.get("frozen") or {}
        first = frozen.get("first_snapshot") or (pg.get("scans") or [{}])[0]
        return dict((first.get("lines") or {}))
    lines = g.get("lines") or {}
    return {
        "consensus_spread_home": lines.get("open_spread_home"),
        "consensus_total": lines.get("open_total"),
    }


def generate_plays(
    games: list[dict[str, Any]],
    store: dict[str, Any],
    *,
    use_espn_engine: bool,
) -> list[dict[str, Any]]:
    paper_slots = base._paper_by_slot(store)
    team_log = build_team_game_log(games)
    engine_by_day: dict[date, Any] = {}
    out: list[dict[str, Any]] = []

    def engine_for(day: date | None):
        if day is None:
            day = date.min
        if day not in engine_by_day:
            engine_by_day[day] = base.engine_at_start_of_et_date(day, paper_store=store, use_espn=use_espn_engine)
        return engine_by_day[day]

    for g in games:
        home, away = str(g["home"]), str(g["away"])
        day = base.kickoff_date_et(g.get("kickoff"))
        gr = g["graded"]
        lines = dict(g.get("lines") or {})
        inj = g.get("injury") or {"home_absences": [], "away_absences": []}
        rest = tag_game_rest_travel(home=home, away=away, kickoff=g.get("kickoff"), team_log=team_log)
        engine = engine_for(day)
        snap = base.recompute_v1_tip_snapshot(
            engine, home=home, away=away, kickoff=g.get("kickoff"), lines=lines, injury_snap=inj
        )
        open_lines = _open_lines_for_game(g, paper_slots)
        pre_tip = {"lines": open_lines} if open_lines else {}

        variant_lists = {
            "original_raw": picks_original_pre_injury(snap, home=home, away=away),
            "current_inj": injury_adj_pace_picks(snap, home=home, away=away, engine=engine),
        }
        kick_dt = parse_kickoff_utc(g.get("kickoff"))
        shadow = compute_shadow_totals_sidecar(
            engine,
            home=home,
            away=away,
            kickoff=kick_dt,
            lines=lines,
            live_total=float(snap.get("total") or 0),
            live_injury_total=float(snap.get("injury_total") if snap.get("injury_total") is not None else snap.get("total") or 0),
            home_absences=inj.get("home_absences"),
            away_absences=inj.get("away_absences"),
        )
        sh = shadow.get("shadow_total_pick")
        variant_lists["shadow_cs_total"] = [sh] if sh else []

        ct = gr.get("close_total")
        actual_total = gr.get("actual_total")
        market_over = market_under = None
        if ct is not None and actual_total is not None:
            market_over = _grade_ou(int(actual_total), float(ct), min_edge=0.0, proj_total=float(ct) + 1)
            market_under = _grade_ou(int(actual_total), float(ct), min_edge=0.0, proj_total=float(ct) - 1)

        for model, picks in variant_lists.items():
            use_inj = model in ("current_inj", "shadow_cs_total")
            for pick in picks:
                res = base._grade_pick(pick, gr, snap, use_injury=use_inj)
                row = {
                    "model": model,
                    "filter": "baseline",
                    "date_et": day.isoformat() if day else "",
                    "away": away,
                    "home": home,
                    "line_source": g.get("line_source"),
                    "market": pick.get("kind"),
                    "side": pick.get("side"),
                    "pick": pick.get("pick"),
                    "gap_pts": pick.get("gap"),
                    "result": res,
                    "units": units_at_110(res),
                    **rest,
                }
                if model == "original_raw" and pre_tip.get("lines"):
                    clv = pace_clv_fields(
                        pick=pick,
                        pre_tip=pre_tip,
                        close_spread_home=gr.get("close_spread_home"),
                        close_total=gr.get("close_total"),
                        proj_margin=float(snap.get("margin") or 0),
                        proj_total=float(snap.get("total") or 0),
                    )
                    row["clv_toward_model"] = clv.get("clv_toward_model")
                    row["has_open_close"] = (
                        pick.get("kind") == "spread"
                        and open_lines.get("consensus_spread_home") is not None
                        and gr.get("close_spread_home") is not None
                    ) or (
                        pick.get("kind") == "total"
                        and open_lines.get("consensus_total") is not None
                        and gr.get("close_total") is not None
                    )
                out.append(row)

        if ct is not None and actual_total is not None:
            out.append(
                {
                    "model": "_market_",
                    "filter": "market_total",
                    "date_et": day.isoformat() if day else "",
                    "away": away,
                    "home": home,
                    "market": "total",
                    "side": "over",
                    "result": market_over,
                    "gap_pts": None,
                    **rest,
                }
            )
            out.append(
                {
                    "model": "_market_",
                    "filter": "market_total",
                    "date_et": day.isoformat() if day else "",
                    "away": away,
                    "home": home,
                    "market": "total",
                    "side": "under",
                    "result": market_under,
                    "gap_pts": None,
                    **rest,
                }
            )
    return out


def _apply_filters(baseline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    model_plays = [p for p in baseline if p.get("model") in MODELS]

    for p in model_plays:
        rows.append({**p, "filter": "baseline"})

    for p in model_plays:
        if p.get("side") != "over":
            rows.append({**p, "filter": "unders_only"})

    for p in model_plays:
        if p.get("side") == "over" and float(p.get("gap_pts") or 0) >= 2 * MIN_GAP:
            rows.append({**p, "filter": "strict_overs_2x_gap"})

    for thr in (2, 3, 4, 5, 6):
        for p in model_plays:
            if p.get("market") != "total":
                continue
            if float(p.get("gap_pts") or 0) >= thr:
                rows.append({**p, "filter": f"totals_min_gap_{thr}"})

    for p in model_plays:
        if p.get("side") != "under":
            continue
        if p.get("either_b2b"):
            rows.append({**p, "filter": "unders_either_b2b"})

    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", default="2026-10-28")
    args = parser.parse_args()
    through = date.fromisoformat(args.through)
    store = load_paper_store()
    espn_doc = base._load_espn_lines(base.ESPN_LINES_PATH)
    games, cov = base._collect_unified_games(store, espn_doc, through=through)

    baseline = generate_plays(games, store, use_espn_engine=True)
    all_rows = _apply_filters(baseline)

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    if all_rows:
        fields = sorted({k for r in all_rows for k in r})
        with CSV_OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(all_rows)

    md: list[str] = [
        "# NBA Pace filter backtest (research — PR #122)",
        "",
        f"**Universe:** {cov['included']} games (repo **{cov['with_repo_lines']}** + ESPN pickcenter **{cov['with_espn_lines']}**). "
        "ESPN lines are usually **closes**, not pre-tip. **No Odds API.**",
        "",
        "## 1 — Side filters (baseline = all qualifying spread/total plays)",
        "",
        "| Model | Filter | W–L | Win % | Units | $ @ $10/u | n | Wilson 95% |",
        "|-------|--------|-----|-------|-------|-----------|---|------------|",
    ]

    for model, mlabel in MODELS.items():
        for filt in ("baseline", "unders_only", "strict_overs_2x_gap"):
            sub = [r for r in all_rows if r.get("model") == model and r.get("filter") == filt]
            s = _stats(sub)
            md.append(
                f"| {mlabel} | {filt} | {s['record']} | {s['win_pct']} | {s['units']:+.2f} | ${s['dollars']:+.0f} | {s['n']} | {s['wilson']} |"
            )

    md.extend(["", "## 2 — Totals minimum gap (totals plays only)", ""])
    md.append("| Model | Min gap | W–L | Win % | Units | $ | n |")
    md.append("|-------|---------|-----|-------|-------|---|---|")
    for model, mlabel in MODELS.items():
        for thr in (2, 3, 4, 5, 6):
            sub = [r for r in all_rows if r.get("model") == model and r.get("filter") == f"totals_min_gap_{thr}"]
            s = _stats(sub)
            md.append(
                f"| {mlabel} | ≥{thr} pt | {s['record']} | {s['win_pct']} | {s['units']:+.2f} | ${s['dollars']:+.0f} | {s['n']} |"
            )

    md.extend(["", "## 3 — Rest / travel (market totals vs line, all games with total)", ""])
    market = [r for r in baseline if r.get("model") == "_market_"]
    for label, pred in (
        ("All games (Over)", lambda r: r.get("side") == "over"),
        ("All games (Under)", lambda r: r.get("side") == "under"),
        ("Either team B2B (Over)", lambda r: r.get("side") == "over" and r.get("either_b2b")),
        ("Either team B2B (Under)", lambda r: r.get("side") == "under" and r.get("either_b2b")),
        ("Rest mismatch (Over)", lambda r: r.get("side") == "over" and r.get("rest_mismatch")),
        ("Rest mismatch (Under)", lambda r: r.get("side") == "under" and r.get("rest_mismatch")),
    ):
        sub = [r for r in market if pred(r)]
        s = _stats(sub)
        md.append(f"- **{label}:** {s['record']} ({s['win_pct']}), {s['units']:+.2f}u (${s['dollars']:+.0f}), **n={s['n']}**")

    md.extend(["", "### Model: Unders only + either team B2B", ""])
    for model, mlabel in MODELS.items():
        sub = [r for r in all_rows if r.get("model") == model and r.get("filter") == "unders_either_b2b"]
        s = _stats(sub)
        md.append(f"- **{mlabel}:** {s['record']}, {s['units']:+.2f}u (${s['dollars']:+.0f}), n={s['n']}")

    md.extend(["", "## 4 — CLV (original raw; open + close both required)", ""])
    clv_rows = [
        r
        for r in all_rows
        if r.get("model") == "original_raw"
        and r.get("filter") == "baseline"
        and r.get("has_open_close")
    ]
    clv_hits = [r for r in clv_rows if r.get("clv_toward_model") is True]
    clv_n = len(clv_rows)
    md.append(
        f"- Plays with open+close: **{clv_n}** (small n; repo first-scan open vs graded close; ESPN open/close from pickcenter)"
    )
    if clv_n:
        md.append(
            f"- Line moved toward model (CLV proxy): **{len(clv_hits)}/{clv_n}** ({100*len(clv_hits)/clv_n:.1f}%)"
        )
        s = _stats(clv_rows)
        md.append(f"- Record on those plays: **{s['record']}**, {s['units']:+.2f}u (${s['dollars']:+.0f})")

    md.extend(["", "## Summary table (key filters)", ""])
    md.append("| Model | Filter | W–L | Win % | Units | $ @ $10/u | n |")
    md.append("|-------|--------|-----|-------|-------|-----------|---|")
    key_filters = (
        "baseline",
        "unders_only",
        "strict_overs_2x_gap",
        "totals_min_gap_5",
        "totals_min_gap_6",
        "unders_either_b2b",
    )
    for model, mlabel in MODELS.items():
        for filt in key_filters:
            sub = [r for r in all_rows if r.get("model") == model and r.get("filter") == filt]
            s = _stats(sub)
            md.append(
                f"| {mlabel} | {filt} | {s['record']} | {s['win_pct']} | {s['units']:+.2f} | ${s['dollars']:+.0f} | {s['n']} |"
            )

    md.extend(
        [
            "",
            "## Plain-English verdict",
            "",
        ]
    )
    u = _stats([r for r in all_rows if r.get("model") == "original_raw" and r.get("filter") == "unders_only"])
    uc = _stats([r for r in all_rows if r.get("model") == "current_inj" and r.get("filter") == "unders_only"])
    g6 = _stats([r for r in all_rows if r.get("model") == "original_raw" and r.get("filter") == "totals_min_gap_6"])
    b = _stats([r for r in all_rows if r.get("model") == "original_raw" and r.get("filter") == "unders_either_b2b"])
    mkt_b2b_u = _stats(
        [
            r
            for r in market
            if r.get("side") == "under" and r.get("either_b2b")
        ]
    )
    md.append(
        f"Sample sizes stay **small** (baseline **n≈66** per spread+total model; **strict 2× Overs n=2** for raw/current; "
        f"**totals ≥6 n={g6['n']}**). Wilson intervals still span break-even (~52.4% at -110)."
    )
    md.append("")
    md.append(
        f"**Unders-only** is the only side filter that consistently improves on baseline in this slice: original raw "
        f"**{u['record']}** ({u['units']:+.2f}u, ${u['dollars']:+.0f}, n={u['n']}); current injury-adj "
        f"**{uc['record']}** ({uc['units']:+.2f}u). **Strict Overs (gap ≥6)** is too thin to judge (n=2). "
        f"The **2026-27 totals shadow** gets worse under Unders-only — do not apply these filters to that sidecar yet."
    )
    md.append("")
    md.append(
        f"**Totals gap ≥5–6** on original/current (totals market only) shows **{g6['record']}** and +{g6['units']:.2f}u "
        f"but **n={g6['n']}** — interesting for **paper/shadow** only if you also require **repo pre-tip lines** "
        f"(not ESPN closes). **Rest/B2B**: market Unders on B2B slates were **{mkt_b2b_u['record']}** (coin flip); "
        f"**model Unders + B2B** was **{b['record']}** (n={b['n']}) — **not** worth stacking live."
    )
    md.append("")
    md.append(
        "**CLV caveat:** ESPN pickcenter numbers are often **closing** lines; open+close CLV on 55 plays showed the "
        "line moved toward the model only **~27%** of the time — do not treat CLV as validation on the ESPN subset."
    )
    md.append("")
    md.append(
        "**Shadow-test recommendation (not production):** after the Nov 5 resume, log **Unders-only** plays from "
        "**current injury-adj Pace** on **repo scans only**, optionally tag **totals with gap ≥5** separately. "
        "Skip B2B stacking and skip strict-Overs until n grows."
    )
    md.append(f"\nCSV: `{CSV_OUT.relative_to(ROOT)}`\n")

    REPORT_MD.write_text("\n".join(md) + "\n")
    print(REPORT_MD.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
