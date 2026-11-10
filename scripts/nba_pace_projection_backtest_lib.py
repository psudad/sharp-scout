"""Walk-forward NBA Pace projection metrics (research only, no live picks)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable

from nba_pace_original_backtest_lib import MIN_GAP, Record, units_at_110
from sharp_scout.config import DATA_DIR
from sharp_scout.data.espn_nba import fetch_espn_nba_finals_by_event
from sharp_scout.nba.score_model.pace_v1 import injury_adj_pace_picks
from sharp_scout.nba.score_model.paper import _merged_lines_from_scans, load_paper_store
from sharp_scout.nba.score_model.replay_engine import engine_at_start_of_et_date
from sharp_scout.nba.score_model.replay_project import recompute_v1_tip_snapshot
from sharp_scout.nba.score_model.state import _season_start_date
from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.utils.kickoff import parse_kickoff_utc
from sharp_scout.utils.slate import ET

ESPN_LINES_PATH = DATA_DIR / "paper" / "nba_espn_pregame_lines.json"


@dataclass
class ProjMetrics:
    n: int = 0
    bias_sum: float = 0.0
    mae_actual_sum: float = 0.0
    mae_close_sum: float = 0.0
    overs: int = 0
    unders: int = 0

    def add(self, proj: float, actual: float, close: float | None) -> None:
        self.n += 1
        self.bias_sum += proj - actual
        self.mae_actual_sum += abs(proj - actual)
        if close is not None:
            self.mae_close_sum += abs(actual - float(close))
        if proj > actual:
            self.overs += 1
        else:
            self.unders += 1

    def summary(self) -> dict[str, Any]:
        if not self.n:
            return {"n": 0}
        return {
            "n": self.n,
            "mean_bias": round(self.bias_sum / self.n, 3),
            "mae_vs_actual": round(self.mae_actual_sum / self.n, 3),
            "mae_vs_close": round(self.mae_close_sum / self.n, 3) if self.mae_close_sum else None,
            "over_under_split": f"{self.overs}/{self.unders}",
        }


def _load_espn_lines(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"games": []}
    import json

    return json.loads(path.read_text())


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


def collect_unified_games(
    store: dict[str, Any],
    espn_doc: dict[str, Any],
    *,
    season_start: date,
    through: date,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    stats = {"with_repo_lines": 0, "with_espn_lines": 0, "included": 0}
    paper_slots: dict[tuple[str, str, str], dict[str, Any]] = {}
    for g in store.get("games") or []:
        day = kickoff_date_et(g.get("kickoff"))
        if day is None:
            continue
        paper_slots[(str(g.get("away")), str(g.get("home")), day.isoformat())] = g

    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []

    for g in store.get("games") or []:
        if not g.get("graded"):
            continue
        day = kickoff_date_et(g.get("kickoff"))
        if day is None or day < season_start or day > through:
            continue
        slot = (str(g.get("away")), str(g.get("home")), day.isoformat())
        tip = _tip_src(g)
        lines = dict(tip.get("lines") or {})
        if lines.get("consensus_total") is None:
            continue
        stats["with_repo_lines"] += 1
        stats["included"] += 1
        seen.add(slot)
        out.append(
            {
                "away": slot[0],
                "home": slot[1],
                "kickoff": g.get("kickoff"),
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
        if day < season_start or day > through:
            continue
        slot = (str(eg.get("away")), str(eg.get("home")), day_s)
        if slot in seen:
            continue
        lines = dict(eg.get("lines") or {})
        if lines.get("consensus_total") is None:
            continue
        hs, as_ = int(eg["espn_home_score"]), int(eg["espn_away_score"])
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
        seen.add(slot)
        out.append(
            {
                "away": slot[0],
                "home": slot[1],
                "kickoff": eg.get("kickoff"),
                "line_source": "espn_pickcenter",
                "lines": lines,
                "injury": inj,
                "graded": {
                    "actual_margin": hs - as_,
                    "actual_total": hs + as_,
                    "close_spread_home": lines.get("consensus_spread_home"),
                    "close_total": lines.get("consensus_total"),
                },
            }
        )

    out.sort(key=lambda x: parse_kickoff_utc(x.get("kickoff")) or datetime.min.replace(tzinfo=timezone.utc))
    return out, stats


def season_bounds(season_label: str) -> tuple[date, date]:
    """NBA season label like 2025-26 -> Oct 1 2025 through Jun 30 2026 ET."""
    start_y = int(season_label.split("-")[0])
    return date(start_y, 10, 1), date(start_y + 1, 6, 30)


def run_projection_backtest(
    *,
    season_start: date,
    through: date,
    paper_path: Path,
    espn_lines_path: Path = ESPN_LINES_PATH,
    pick_fn: Callable[..., list[dict[str, Any]]] | None = None,
    label: str = "baseline",
) -> dict[str, Any]:
    store = load_paper_store(paper_path)
    espn_doc = _load_espn_lines(espn_lines_path)
    games, line_stats = collect_unified_games(
        store, espn_doc, season_start=season_start, through=through
    )
    pick_fn = pick_fn or injury_adj_pace_picks

    engine_by_day: dict[date, Any] = {}

    def _engine_for(day: date | None) -> Any:
        if day is None:
            day = date.min
        if day not in engine_by_day:
            engine_by_day[day] = engine_at_start_of_et_date(day, paper_store=store, use_espn=True)
        return engine_by_day[day]

    all_proj = ProjMetrics()
    pick_proj = ProjMetrics()
    totals_rec = Record()
    over_rec = Record()
    under_rec = Record()

    for g in games:
        home, away = str(g["home"]), str(g["away"])
        day = kickoff_date_et(g.get("kickoff"))
        gr = g["graded"]
        lines = dict(g.get("lines") or {})
        inj = g.get("injury") or {"home_absences": [], "away_absences": []}
        engine = _engine_for(day)
        snap = recompute_v1_tip_snapshot(
            engine, home=home, away=away, kickoff=g.get("kickoff"), lines=lines, injury_snap=inj
        )
        actual = int(gr["actual_total"])
        close = gr.get("close_total")
        proj = float(
            snap.get("injury_total") if snap.get("injury_total") is not None else snap.get("total") or 0
        )
        all_proj.add(proj, float(actual), float(close) if close is not None else None)

        picks = pick_fn(snap, home=home, away=away, engine=engine)
        for pick in picks:
            if pick.get("kind") != "total":
                continue
            side = pick.get("side")
            ct = float(close) if close is not None else float(lines.get("consensus_total") or 0)
            res = "win" if (side == "over" and actual > ct) or (side == "under" and actual < ct) else (
                "push" if actual == ct else "loss"
            )
            totals_rec.add(res)
            pick_proj.add(proj, float(actual), float(close) if close is not None else None)
            if side == "over":
                over_rec.add(res)
            else:
                under_rec.add(res)

    return {
        "label": label,
        "season_start": season_start.isoformat(),
        "through": through.isoformat(),
        "line_stats": line_stats,
        "all_games_projection": all_proj.summary(),
        "pick_games_projection": pick_proj.summary(),
        "totals_picks": {
            "record": totals_rec.wl(),
            "n": totals_rec.n,
            "units_1u_110": round(totals_rec.units, 2),
            "overs": over_rec.wl(),
            "unders": under_rec.wl(),
        },
    }


def format_backtest_table(before: dict[str, Any], after: dict[str, Any]) -> str:
    rows = [
        ("Metric", "Before", "After"),
        ("Games w/ line", str(before["line_stats"]["included"]), str(after["line_stats"]["included"])),
    ]
    for key, title in (
        ("all_games_projection", "All games (injury-adj total)"),
        ("pick_games_projection", "Totals picks only (gap≥{})".format(MIN_GAP)),
    ):
        b, a = before[key], after[key]
        rows.append((f"{title} — mean bias", str(b.get("mean_bias", "—")), str(a.get("mean_bias", "—"))))
        rows.append((f"{title} — MAE vs actual", str(b.get("mae_vs_actual", "—")), str(a.get("mae_vs_actual", "—"))))
        rows.append((f"{title} — MAE vs close", str(b.get("mae_vs_close", "—")), str(a.get("mae_vs_close", "—"))))
    bt, at = before["totals_picks"], after["totals_picks"]
    rows.append(("Totals pick record", bt["record"], at["record"]))
    rows.append(("Totals pick units @1u", f"{bt['units_1u_110']:+.2f}", f"{at['units_1u_110']:+.2f}"))
    rows.append(("O/U pick split", f"O {bt['overs']} / U {bt['unders']}", f"O {at['overs']} / U {at['unders']}"))
    md = "| " + " | ".join(rows[0]) + " |\n"
    md += "|" + "|".join(["---"] * len(rows[0])) + "|\n"
    for r in rows[1:]:
        md += "| " + " | ".join(r) + " |\n"
    return md
