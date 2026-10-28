"""Mechanical Pace v1 qualifications (separate from Jason's official card)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.nba.slate_et import kickoff_date_et

MECHANICAL_PATH = DATA_DIR / "paper" / "nba_pace_mechanical.json"
MECHANICAL_CSV_PATH = DATA_DIR / "paper" / "nba_pace_mechanical.csv"


def load_mechanical_pace(path: Path | None = None) -> dict[str, Any]:
    p = path or MECHANICAL_PATH
    if not p.exists():
        return {"version": 1, "plays": [], "updated_at": None}
    raw = json.loads(p.read_text())
    raw.setdefault("plays", [])
    return raw


def save_mechanical_pace(store: dict[str, Any], path: Path | None = None) -> None:
    p = path or MECHANICAL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")
    _write_csv(store)


def _write_csv(store: dict[str, Any]) -> None:
    fields = [
        "id",
        "date_et",
        "away",
        "home",
        "market",
        "pick",
        "gap_pts",
        "result",
        "clv_toward_model",
        "model_error_vs_close",
        "recommended_units",
        "on_official_card",
    ]
    with MECHANICAL_CSV_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in store.get("plays") or []:
            w.writerow({k: r.get(k) for k in fields})


def _slot_key(date_et: str, away: str, home: str, market: str) -> tuple[str, str, str, str]:
    return (date_et, away, home, market)


def log_mechanical_play(entry: dict[str, Any], *, store: dict[str, Any] | None = None) -> bool:
    store = store or load_mechanical_pace()
    slot = _slot_key(
        str(entry.get("date_et") or ""),
        str(entry.get("away") or ""),
        str(entry.get("home") or ""),
        str(entry.get("market") or ""),
    )
    for p in store.get("plays") or []:
        if _slot_key(
            str(p.get("date_et") or ""),
            str(p.get("away") or ""),
            str(p.get("home") or ""),
            str(p.get("market") or ""),
        ) == slot:
            return False
    store.setdefault("plays", []).append(entry)
    save_mechanical_pace(store)
    return True


def sync_mechanical_pace_from_paper_store(paper_store: dict[str, Any] | None = None) -> int:
    """Log v1 mechanical qualifiers (model gap rules) — never the official Jason card."""
    from sharp_scout.nba.score_model.official_pace import (
        last_official_backfill_date_et,
        load_official_pace,
        pace_display_pick_from_snapshot,
    )
    from sharp_scout.nba.score_model.pace_v1 import recommended_unit_fraction
    from sharp_scout.nba.score_model.paper import _game_excluded, _grade_ats_margin, _grade_ou
    from sharp_scout.nba.score_model.state import ensure_score_engine

    paper_store = paper_store or {}
    added = 0
    store = load_mechanical_pace()
    engine = ensure_score_engine()
    backfill_through = last_official_backfill_date_et(load_official_pace())
    for g in paper_store.get("games") or []:
        if _game_excluded(g) or not g.get("graded"):
            continue
        day = kickoff_date_et(g.get("kickoff"))
        if day is None:
            continue
        if backfill_through is not None and day <= backfill_through:
            continue
        frozen = g.get("frozen") or {}
        if frozen.get("pace_published_pick"):
            continue
        snap = frozen.get("snapshot") or (g.get("scans") or [{}])[-1]
        home, away = str(g.get("home") or ""), str(g.get("away") or "")
        pick = frozen.get("pace_display_pick") or pace_display_pick_from_snapshot(
            snap, home=home, away=away, engine=engine
        )
        if not pick:
            continue
        gr = g["graded"]
        cs, ct = gr.get("close_spread_home"), gr.get("close_total")
        pm_i = float(
            snap.get("injury_margin") if snap.get("injury_margin") is not None else snap.get("margin") or 0
        )
        pt_i = float(
            snap.get("injury_total") if snap.get("injury_total") is not None else snap.get("total") or 0
        )
        act_total = int(gr["actual_total"])
        act_margin = int(gr["actual_margin"])
        if pick["kind"] == "spread" and cs is not None:
            res = _grade_ats_margin(act_margin, cs, min_edge=0.0, proj_margin=pm_i)
        elif pick["kind"] == "total" and ct is not None:
            res = _grade_ou(act_total, ct, min_edge=0.0, proj_total=pt_i)
        else:
            continue
        if res not in ("win", "loss", "push"):
            continue
        units = recommended_unit_fraction(snap, pick, home=home, away=away, engine=engine)
        entry = {
            "id": f"mech-{g.get('event_id')}-{pick.get('kind')}",
            "date_et": day.isoformat(),
            "kickoff": g.get("kickoff"),
            "away": away,
            "home": home,
            "market": pick.get("kind"),
            "pick": pick.get("pick"),
            "gap_pts": round(float(pick.get("gap") or 0), 2),
            "result": res,
            "recommended_units": units,
            "on_official_card": False,
        }
        if log_mechanical_play(entry, store=store):
            added += 1
    return added
