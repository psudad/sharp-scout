#!/usr/bin/env python3
"""Backtest: original Pace rules vs current live vs 2026-27 totals shadow (research only)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from nba_pace_original_backtest_lib import (  # noqa: E402
    ORIGINAL_POST_INJURY_COMMIT,
    ORIGINAL_PRE_INJURY_COMMIT,
    MIN_GAP,
    Record,
    gap_bucket,
    n_needed_for_break_even,
    picks_current_raw,
    picks_original_b913bcb,
    picks_original_pre_injury,
    units_at_110,
    wilson_ci,
)
from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.data.espn_nba import fetch_espn_nba_finals_by_event  # noqa: E402
from sharp_scout.nba.score_model.pace_v1 import injury_adj_pace_picks  # noqa: E402
from sharp_scout.nba.score_model.paper import (  # noqa: E402
    _grade_ats_margin,
    _grade_ou,
    _merged_lines_from_scans,
    load_paper_store,
)
from sharp_scout.nba.score_model.replay_engine import engine_at_start_of_et_date  # noqa: E402
from sharp_scout.nba.score_model.replay_project import recompute_v1_tip_snapshot  # noqa: E402
from sharp_scout.nba.score_model.state import _season_start_date  # noqa: E402
from sharp_scout.nba.score_model.totals_shadow import compute_shadow_totals_sidecar  # noqa: E402
from sharp_scout.nba.slate_et import kickoff_date_et  # noqa: E402
from sharp_scout.utils.kickoff import parse_kickoff_utc  # noqa: E402
from sharp_scout.utils.slate import ET  # noqa: E402

REPORT_MD = ROOT / "docs" / "nba_pace_original_backtest.md"
CSV_OUT = ROOT / "data" / "paper" / "nba_pace_original_backtest.csv"
ESPN_LINES_PATH = DATA_DIR / "paper" / "nba_espn_pregame_lines.json"


def _tip_src(g: dict[str, Any]) -> dict[str, Any]:
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


def _grade_pick(pick: dict[str, Any], gr: dict[str, Any], snap: dict[str, Any], *, use_injury: bool) -> str | None:
    cs, ct = gr.get("close_spread_home"), gr.get("close_total")
    if pick["kind"] == "spread" and cs is not None:
        pm = float(
            snap.get("injury_margin") if use_injury and snap.get("injury_margin") is not None else snap.get("margin") or 0
        )
        return _grade_ats_margin(int(gr["actual_margin"]), cs, min_edge=0.0, proj_margin=pm)
    if pick["kind"] == "total" and ct is not None:
        pt = float(
            snap.get("injury_total") if use_injury and snap.get("injury_total") is not None else snap.get("total") or 0
        )
        return _grade_ou(int(gr["actual_total"]), ct, min_edge=0.0, proj_total=pt)
    return None


def _load_espn_lines(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"games": []}
    return json.loads(path.read_text())


def _paper_by_slot(store: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for g in store.get("games") or []:
        day = kickoff_date_et(g.get("kickoff"))
        if day is None:
            continue
        out[(str(g.get("away")), str(g.get("home")), day.isoformat())] = g
    return out


def _collect_unified_games(
    store: dict[str, Any],
    espn_doc: dict[str, Any],
    *,
    through: date,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Unified backtest rows: repo pre-tip lines + ESPN pickcenter backfill."""
    stats = {
        "espn_season_finals": 0,
        "with_repo_lines": 0,
        "with_espn_lines": 0,
        "included": 0,
        "still_missing": 0,
    }
    paper_slots = _paper_by_slot(store)
    seen_slots: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []

    for g in store.get("games") or []:
        if not g.get("graded"):
            continue
        day = kickoff_date_et(g.get("kickoff"))
        if day is None or day > through:
            continue
        slot = (str(g.get("away")), str(g.get("home")), day.isoformat())
        tip = _tip_src(g)
        lines = dict(tip.get("lines") or {})
        if lines.get("consensus_spread_home") is None and lines.get("consensus_total") is None:
            continue
        stats["with_repo_lines"] += 1
        stats["included"] += 1
        seen_slots.add(slot)
        out.append(
            {
                "away": slot[0],
                "home": slot[1],
                "kickoff": g.get("kickoff"),
                "event_id": g.get("event_id"),
                "line_source": "repo_odds_api",
                "lines": lines,
                "injury": {
                    "home_absences": tip.get("home_absences") or [],
                    "away_absences": tip.get("away_absences") or [],
                },
                "graded": g["graded"],
            }
        )

    for eg in espn_doc.get("games") or []:
        day_s = str(eg.get("date_et") or "")
        try:
            day = date.fromisoformat(day_s)
        except ValueError:
            continue
        if day > through:
            continue
        slot = (str(eg.get("away")), str(eg.get("home")), day_s)
        if slot in seen_slots:
            continue
        lines = dict(eg.get("lines") or {})
        if lines.get("consensus_spread_home") is None and lines.get("consensus_total") is None:
            continue
        hs = int(eg["espn_home_score"])
        as_ = int(eg["espn_away_score"])
        cs = lines.get("consensus_spread_home")
        ct = lines.get("consensus_total")
        paper_g = paper_slots.get(slot)
        inj = {"home_absences": [], "away_absences": []}
        if paper_g:
            tip = _tip_src(paper_g)
            inj = {
                "home_absences": tip.get("home_absences") or [],
                "away_absences": tip.get("away_absences") or [],
            }
        stats["with_espn_lines"] += 1
        stats["included"] += 1
        seen_slots.add(slot)
        out.append(
            {
                "away": slot[0],
                "home": slot[1],
                "kickoff": eg.get("kickoff"),
                "event_id": eg.get("espn_event_id"),
                "line_source": "espn_pickcenter",
                "lines": lines,
                "injury": inj,
                "graded": {
                    "actual_margin": hs - as_,
                    "actual_total": hs + as_,
                    "close_spread_home": cs,
                    "close_total": ct,
                },
            }
        )

    season_start = _season_start_date(datetime.combine(through, time(12, 0), tzinfo=ET))
    since = datetime.combine(season_start, datetime.min.time(), tzinfo=timezone.utc)
    until = datetime.combine(through, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
    try:
        scores = fetch_espn_nba_finals_by_event(since=since, until=until)
    except Exception:
        scores = []
    for s in scores:
        kick = parse_kickoff_utc(s.get("kickoff"))
        day = kickoff_date_et(kick)
        if day is None or day > through:
            continue
        stats["espn_season_finals"] += 1
        slot = (str(s["away_team"]), str(s["home_team"]), day.isoformat())
        if slot not in seen_slots:
            stats["still_missing"] += 1

    out.sort(key=lambda x: parse_kickoff_utc(x.get("kickoff")) or datetime.min.replace(tzinfo=timezone.utc))
    return out, stats


def _espn_games_through(through: date) -> int:
    season_start = _season_start_date(datetime.combine(through, time(12, 0), tzinfo=ET))
    since = datetime.combine(season_start, datetime.min.time(), tzinfo=timezone.utc)
    until = datetime.combine(through, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
    try:
        scores = fetch_espn_nba_finals_by_event(since=since, until=until)
    except Exception:
        return 0
    n = 0
    for s in scores:
        kick = parse_kickoff_utc(s.get("kickoff"))
        d = kickoff_date_et(kick)
        if d is not None and d <= through:
            n += 1
    return n


def _summarize_plays(
    plays: list[dict[str, Any]], model: str, *, line_source: str | None = None
) -> dict[str, Any]:
    overall = Record()
    spreads = Record()
    totals = Record()
    buckets: dict[str, Record] = defaultdict(Record)
    over = Record()
    under = Record()
    for r in plays:
        if r.get("model") != model:
            continue
        if line_source is not None and r.get("line_source") != line_source:
            continue
        res = r.get("result")
        overall.add(res)
        kind = r.get("market")
        if kind == "spread":
            spreads.add(res)
        elif kind == "total":
            totals.add(res)
            if r.get("side") == "over":
                over.add(res)
            else:
                under.add(res)
        buckets[gap_bucket(r.get("gap_pts"))].add(res)
    return {
        "overall": overall,
        "spreads": spreads,
        "totals": totals,
        "buckets": dict(buckets),
        "over": over,
        "under": under,
    }


def _md_table_row(label: str, rec: Record) -> str:
    ci = wilson_ci(rec.wins, rec.n)
    ci_s = f"{100*ci[0]:.1f}–{100*ci[1]:.1f}%" if rec.n else "—"
    return f"| {label} | {rec.wl()} | {rec.n} | {rec.units:+.2f}u | {ci_s} |"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", default="2026-10-28", help="Last ET slate date (inclusive)")
    parser.add_argument("--paper", type=Path, default=DATA_DIR / "paper" / "nba_score_model.json")
    parser.add_argument("--espn-lines", type=Path, default=ESPN_LINES_PATH)
    parser.add_argument("--no-espn", action="store_true", help="Skip walk-forward ESPN game logs in engine")
    args = parser.parse_args()
    through = date.fromisoformat(args.through)
    store = load_paper_store(args.paper)
    espn_doc = _load_espn_lines(args.espn_lines)
    games, line_stats = _collect_unified_games(store, espn_doc, through=through)

    per_play: list[dict[str, Any]] = []
    engine_by_day: dict[date, Any] = {}

    def _engine_for(day: date | None) -> Any:
        if day is None:
            day = date.min
        if day not in engine_by_day:
            engine_by_day[day] = engine_at_start_of_et_date(day, paper_store=store, use_espn=not args.no_espn)
        return engine_by_day[day]

    for g in games:
        home, away = str(g["home"]), str(g["away"])
        day = kickoff_date_et(g.get("kickoff"))
        gr = g["graded"]
        lines = dict(g.get("lines") or {})
        inj = g.get("injury") or {"home_absences": [], "away_absences": []}
        line_source = str(g.get("line_source") or "unknown")
        engine = _engine_for(day)
        snap = recompute_v1_tip_snapshot(
            engine, home=home, away=away, kickoff=g.get("kickoff"), lines=lines, injury_snap=inj
        )

        variant_lists: dict[str, list[dict[str, Any]]] = {
            "original": picks_original_pre_injury(snap, home=home, away=away),
            "original_inj_b913bcb": picks_original_b913bcb(snap, home=home, away=away),
            "current_raw": picks_current_raw(snap, home=home, away=away),
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
        sh_pick = shadow.get("shadow_total_pick")
        variant_lists["shadow_cs_total"] = [sh_pick] if sh_pick else []

        for model, picks in variant_lists.items():
            use_inj = model in ("current_inj", "original_inj_b913bcb", "shadow_cs_total")
            for pick in picks:
                res = _grade_pick(pick, gr, snap, use_injury=use_inj)
                per_play.append(
                    {
                        "model": model,
                        "date_et": day.isoformat() if day else "",
                        "away": away,
                        "home": home,
                        "kickoff": g.get("kickoff"),
                        "event_id": g.get("event_id"),
                        "line_source": line_source,
                        "market": pick.get("kind"),
                        "pick": pick.get("pick"),
                        "side": pick.get("side"),
                        "line": pick.get("line"),
                        "gap_pts": pick.get("gap"),
                        "gap_bucket": gap_bucket(pick.get("gap")),
                        "result": res,
                        "units": units_at_110(res),
                        "close_spread_home": gr.get("close_spread_home"),
                        "close_total": gr.get("close_total"),
                        "actual_margin": gr.get("actual_margin"),
                        "actual_total": gr.get("actual_total"),
                        "raw_margin": snap.get("margin"),
                        "raw_total": snap.get("total"),
                        "injury_margin": snap.get("injury_margin"),
                        "injury_total": snap.get("injury_total"),
                    }
                )

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    if per_play:
        fields = list(per_play[0].keys())
        with CSV_OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(per_play)

    model_keys = (
        "original",
        "original_inj_b913bcb",
        "current_raw",
        "current_inj",
        "shadow_cs_total",
    )
    summaries = {k: _summarize_plays(per_play, k) for k in model_keys}

    def _played(model: str, away: str, home: str, needle: str) -> bool:
        for r in per_play:
            if r.get("model") != model or r.get("away") != away or r.get("home") != home:
                continue
            if needle in str(r.get("pick") or ""):
                return True
        return False

    def _night_record(model: str, day: str) -> str:
        sub = [r for r in per_play if r.get("model") == model and r.get("date_et") == day]
        w = sum(1 for r in sub if r.get("result") == "win")
        l = sum(1 for r in sub if r.get("result") == "loss")
        return f"{w}-{l} ({len(sub)} plays)"

    oct28_q = [
        "DEN @ NOP Over: original="
        + ("yes" if _played("original", "DEN", "NOP", "Over") else "no")
        + ", current_inj="
        + ("yes" if _played("current_inj", "DEN", "NOP", "Over") else "no"),
        "LAL @ LAC Over: original="
        + ("yes" if _played("original", "LAL", "LAC", "Over") else "no")
        + ", current_inj="
        + ("yes" if _played("current_inj", "LAL", "LAC", "Over") else "no"),
    ]

    md: list[str] = [
        "# NBA Pace of Play — original vs live backtest (research)",
        "",
        "Isolated replay using walk-forward stage-3 engine. Lines: **repo** pre-tip Odds API scans "
        "(`data/paper/nba_score_model.json`) plus **ESPN pickcenter backfill** "
        "(`data/paper/nba_espn_pregame_lines.json`, backtest-only). **Does not change live model code or picks.**",
        "",
        "## Commits identified (git)",
        "",
        f"| Role | SHA | Date (author) | Card logic |",
        f"|------|-----|---------------|------------|",
        f"| **Original (Oct 25–26 winning slates)** | `{ORIGINAL_PRE_INJURY_COMMIT[:12]}` | 2026-10-25 19:29 UTC | Raw stage-3 margin/total vs consensus; **≥{MIN_GAP:g} pt** gap; highest-gap spread or total wins. "
        f"No injury layer on picks (#107 merged Oct 27). |",
        f"| **Pre–#116 snapshot (injury-adj, no later gates)** | `{ORIGINAL_POST_INJURY_COMMIT[:12]}` | 2026-10-28 05:42 UTC | Injury-adjusted margin/total vs line; **≥{MIN_GAP:g} pt**; no raw-gap gate; DTD weight **0.45**; no 0.5× injury scale (#116/#117 not yet on main). |",
        "",
        "Note: Jason’s **4–1** and **5–1** nights match the **Oct 25–26 ET** official backfill (not Oct 21–24). Those slates predate injury-adjusted Pace (#107).",
        "",
        "## Sample coverage",
        "",
        f"- ESPN completed regular-season games through **{through.isoformat()}** (ET): **{line_stats['espn_season_finals']}**",
        f"- Games with **repo** pre-tip lines: **{line_stats['with_repo_lines']}**",
        f"- Games with **ESPN pickcenter** backfill only: **{line_stats['with_espn_lines']}**",
        f"- **Total with any line (target 68):** **{line_stats['included']}**",
        f"- Still missing lines: **{line_stats['still_missing']}**",
        "",
        "### ESPN line caveat",
        "",
        "ESPN summary `pickcenter` numbers are usually **closing** (sometimes **open**) DraftKings/ESPN BET lines — "
        "**not** T−1h pre-tip consensus. For ESPN-only games, the same line is used for model gap **and** grading "
        "(optimistic bias vs real CLV). Repo lines are pre-tip merged scans where available.",
        "",
        "## Head-to-head summary (all {n} games; spread + total may both qualify)".format(
            n=line_stats["included"]
        ),
        "",
        "| Model | W–L | Plays | Units @ 1u −110 | Wilson 95% CI |",
        "|-------|-----|-------|-----------------|---------------|",
    ]
    labels = {
        "original": "Original (raw, pre-injury)",
        "original_inj_b913bcb": "Original (inj-adj @ b913bcb)",
        "current_raw": "Current live (raw)",
        "current_inj": "Current live (injury-adj + raw gate)",
        "shadow_cs_total": "2026-27 totals shadow",
    }
    for key in labels:
        md.append(_md_table_row(labels[key], summaries[key]["overall"]))

    md.extend(["", "### By line source (original raw + current injury-adj)", ""])
    md.append("| Line source | Games | Original raw W–L / u | Current inj-adj W–L / u |")
    md.append("|-------------|-------|----------------------|-------------------------|")
    for src, label in (("repo_odds_api", "Repo pre-tip"), ("espn_pickcenter", "ESPN pickcenter")):
        gcount = line_stats["with_repo_lines"] if src == "repo_odds_api" else line_stats["with_espn_lines"]
        o = _summarize_plays(per_play, "original", line_source=src)["overall"]
        c = _summarize_plays(per_play, "current_inj", line_source=src)["overall"]
        md.append(f"| {label} | {gcount} | {o.wl()} / {o.units:+.2f}u | {c.wl()} / {c.units:+.2f}u |")

    md.extend(["", "#### Subset detail — original raw", ""])
    for src, label in (("repo_odds_api", "Repo"), ("espn_pickcenter", "ESPN")):
        s = _summarize_plays(per_play, "original", line_source=src)
        md.append(
            f"- **{label}:** spreads **{s['spreads'].wl()}** ({s['spreads'].units:+.2f}u), "
            f"totals **{s['totals'].wl()}** ({s['totals'].units:+.2f}u); "
            f"Over **{s['over'].wl()}** / Under **{s['under'].wl()}**; "
            f"gaps 3–5 **{s['buckets'].get('3-5', Record()).wl()}**, "
            f"5–8 **{s['buckets'].get('5-8', Record()).wl()}**, "
            f"8+ **{s['buckets'].get('8+', Record()).wl()}**"
        )

    md.extend(["", "### By market (plays taken)", ""])
    md.append("| Model | Spreads W–L | Spreads u | Totals W–L | Totals u |")
    md.append("|-------|-------------|-----------|------------|----------|")
    for key in labels:
        s = summaries[key]
        md.append(
            f"| {labels[key]} | {s['spreads'].wl()} | {s['spreads'].units:+.2f} | "
            f"{s['totals'].wl()} | {s['totals'].units:+.2f} |"
        )

    md.extend(["", "### Gap buckets (injury-adj gap for current; raw gap for original raw)", ""])
    md.append("| Model | 3–5 | 5–8 | 8+ |")
    md.append("|-------|-----|-----|-----|")
    for key in ("original", "current_inj", "shadow_cs_total"):
        b = summaries[key]["buckets"]
        md.append(
            f"| {labels[key]} | "
            + " | ".join(b.get(k, Record()).wl() for k in ("3-5", "5-8", "8+"))
            + " |"
        )

    md.extend(["", "### Totals: Over vs Under (current injury-adj)", ""])
    ci = summaries["current_inj"]
    md.append(f"- Over: **{ci['over'].wl()}**, {ci['over'].units:+.2f}u")
    md.append(f"- Under: **{ci['under'].wl()}**, {ci['under'].units:+.2f}u")

    md.extend(
        [
            "",
            "## Early official slates (replay check)",
            "",
            f"- **2026-10-25 ET** original raw: **{_night_record('original', '2026-10-25')}** (official backfill **4–1**; DET −1.5 was manual sub-threshold)",
            f"- **2026-10-26 ET** original raw: **{_night_record('original', '2026-10-26')}** (official backfill **5–1**)",
            "",
            "## Oct 28 totals (DEN/NOP, LAL/LAC)",
        ]
    )
    if oct28_q:
        md.extend([f"- {x}" for x in oct28_q])
    else:
        md.append("- No Oct 28 rows with lines in paper store.")

    o = summaries["original"]["overall"]
    c = summaries["current_inj"]["overall"]
    p_hat = o.wins / o.n if o.n else 0.0
    n_need = n_needed_for_break_even(p_hat) if o.n else None
    md.extend(
        [
            "",
            "## Sample-size / break-even caveats",
            "",
            "- Break-even at −110 is **52.38%** (shown as **52.4%**).",
            f"- Original raw: **{100*p_hat:.1f}%** on **{o.n}** plays → Wilson 95% CI "
            f"**{100*wilson_ci(o.wins, o.n)[0]:.1f}–{100*wilson_ci(o.wins, o.n)[1]:.1f}%** (includes 52.4% — cannot reject luck).",
        ]
    )
    if n_need:
        md.append(
            f"- Rough one-sided n to conclude **>{52.4}%** if true rate were {100*p_hat:.1f}%: **~{n_need}** plays (normal approx)."
        )
    else:
        md.append("- Original at or below break-even on this sample; early hot streak alone is not evidence of skill.")
    md.extend(
        [
            f"- Current injury-adj: **{c.wl()}**, **{c.units:+.2f}u** on **{c.n}** plays — underperforms original raw on same slates in this replay.",
            "",
            "## Plain-English verdict",
            "",
        ]
    )
    o_repo = _summarize_plays(per_play, "original", line_source="repo_odds_api")["overall"]
    o_espn = _summarize_plays(per_play, "original", line_source="espn_pickcenter")["overall"]
    verdict = (
        f"With **{line_stats['included']}** games lined (**{line_stats['with_repo_lines']}** repo + **{line_stats['with_espn_lines']}** ESPN), "
        f"original raw is **{o.wl()} ({o.units:+.2f}u)** on **{o.n}** plays — still **below break-even**; Wilson 95% CI spans 52.4%. "
        f"Repo-only subset: **{o_repo.wl()} ({o_repo.units:+.2f}u)**; ESPN pickcenter subset: **{o_espn.wl()} ({o_espn.units:+.2f}u)** "
        "(ESPN lines are likely closes, so this subset is useful for coverage but not for claiming CLV). "
        f"Current injury-adj + raw gate: **{c.wl()} ({c.units:+.2f}u)**. "
        "The Oct 25–26 hot start does **not** extend to the full 68-game sample — treat early wins as **small-n variance**, not validated skill."
    )
    md.append(verdict)
    md.extend(
        [
            "",
            f"ESPN backfill file: `{ESPN_LINES_PATH.relative_to(ROOT)}`",
            f"Per-play CSV: `{CSV_OUT.relative_to(ROOT)}`",
            "",
        ]
    )

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(md) + "\n")
    print(REPORT_MD.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
