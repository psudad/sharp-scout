"""Official Pace of Play paper ledger (Jason card + auto-appended model grades)."""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

OFFICIAL_PATH = DATA_DIR / "paper" / "nba_pace_of_play_official.json"
OFFICIAL_CSV_PATH = DATA_DIR / "paper" / "nba_pace_of_play_official.csv"
MIN_AUTO_GAP = 3.0


def _empty() -> dict[str, Any]:
    return {"version": 1, "notes": "", "plays": [], "updated_at": None}


def load_official_pace(path: Path | None = None) -> dict[str, Any]:
    p = path or OFFICIAL_PATH
    if not p.exists():
        return _empty()
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return _empty()
    raw.setdefault("plays", [])
    return raw


def save_official_pace(store: dict[str, Any], path: Path | None = None) -> None:
    p = path or OFFICIAL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")
    _write_csv(store, OFFICIAL_CSV_PATH)


def _write_csv(store: dict[str, Any], path: Path) -> None:
    rows = store.get("plays") or []
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
        "price",
        "gap_pts",
        "result",
        "units",
        "espn_away_score",
        "espn_home_score",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})


def _units_at_110(result: str) -> float:
    if result == "win":
        return round(100.0 / 110.0, 2)
    if result == "loss":
        return -1.0
    if result == "push":
        return 0.0
    return 0.0


def summarize_official_pace(store: dict[str, Any] | None = None) -> dict[str, Any]:
    store = store or load_official_pace()
    plays = [p for p in store.get("plays") or [] if p.get("result") in ("win", "loss", "push")]
    w = sum(1 for p in plays if p.get("result") == "win")
    l = sum(1 for p in plays if p.get("result") == "loss")
    pu = sum(1 for p in plays if p.get("result") == "push")
    units = round(w * (100.0 / 110.0) - l * 1.0, 2)
    spreads = {"w": 0, "l": 0, "p": 0, "units": 0.0}
    totals = {"w": 0, "l": 0, "p": 0, "units": 0.0}
    for p in plays:
        bucket = spreads if p.get("market") == "spread" else totals
        st = p.get("result")
        if st == "win":
            bucket["w"] += 1
        elif st == "loss":
            bucket["l"] += 1
        elif st == "push":
            bucket["p"] += 1
        bucket["units"] += float(p.get("units") or 0)
    dates = sorted({str(p.get("date_et") or "") for p in plays if p.get("date_et")})
    date_range = ""
    if dates:
        date_range = dates[0] if len(dates) == 1 else f"{dates[0]} – {dates[-1]}"
    denom = w + l
    return {
        "record": f"{w}-{l}" + (f"-{pu}" if pu else ""),
        "wins": w,
        "losses": l,
        "pushes": pu,
        "units": units,
        "win_pct": f"{100.0 * w / denom:.1f}%" if denom else "—",
        "spreads": spreads,
        "totals": totals,
        "n_plays": len(plays),
        "date_range_et": date_range,
    }


def _play_slot_key(
    *,
    date_et: str | None,
    away: str,
    home: str,
    market: str,
) -> tuple[str, str, str, str]:
    return (
        str(date_et or ""),
        normalize_nba_team(str(away)),
        normalize_nba_team(str(home)),
        str(market or ""),
    )


def _play_dedupe_key(p: dict[str, Any]) -> tuple[str, str, str, str]:
    return _play_slot_key(
        date_et=str(p.get("date_et") or ""),
        away=str(p.get("away") or ""),
        home=str(p.get("home") or ""),
        market=str(p.get("market") or ""),
    )


def _slot_already_logged(store: dict[str, Any], slot: tuple[str, str, str, str]) -> bool:
    keys = {_play_dedupe_key(p) for p in store.get("plays") or []}
    return slot in keys


def last_official_backfill_date_et(store: dict[str, Any] | None = None) -> date | None:
    """Latest ET date covered by manual Jason backfill rows."""
    store = store or load_official_pace()
    dates: list[date] = []
    for p in store.get("plays") or []:
        if str(p.get("source") or "") != "official_backfill":
            continue
        raw = p.get("date_et")
        if not raw:
            continue
        try:
            dates.append(date.fromisoformat(str(raw)))
        except ValueError:
            continue
    return max(dates) if dates else None


def injury_adj_pace_picks(
    snap: dict[str, Any],
    *,
    home: str,
    away: str,
    min_gap: float = MIN_AUTO_GAP,
) -> list[dict[str, Any]]:
    lines = snap.get("lines") or {}
    cs, ct = lines.get("consensus_spread_home"), lines.get("consensus_total")
    pm_i = float(
        snap.get("injury_margin") if snap.get("injury_margin") is not None else snap.get("margin") or 0
    )
    pt_i = float(
        snap.get("injury_total") if snap.get("injury_total") is not None else snap.get("total") or 0
    )
    picks: list[dict[str, Any]] = []
    if cs is not None:
        edge = pm_i + float(cs)
        if abs(edge) >= min_gap:
            side = "home" if edge > 0 else "away"
            picks.append(
                {
                    "kind": "spread",
                    "pick": _format_spread_pick(home, away, float(cs), edge),
                    "side": side,
                    "line": float(cs) if side == "home" else -float(cs),
                    "gap": abs(edge),
                }
            )
    if ct is not None:
        edge_t = pt_i - float(ct)
        if abs(edge_t) >= min_gap:
            side = "over" if edge_t > 0 else "under"
            label = "Over" if edge_t > 0 else "Under"
            picks.append(
                {
                    "kind": "total",
                    "pick": f"{away} @ {home}: {label} {float(ct):g}",
                    "side": side,
                    "line": float(ct),
                    "gap": abs(edge_t),
                }
            )
    return picks


def pace_display_pick_from_snapshot(
    snap: dict[str, Any],
    *,
    home: str,
    away: str,
    min_gap: float = MIN_AUTO_GAP,
) -> dict[str, Any] | None:
    """Primary injury-adj Pace card pick at tip (same rule as the public page)."""
    picks = injury_adj_pace_picks(snap, home=home, away=away, min_gap=min_gap)
    if not picks:
        return None
    return max(picks, key=lambda x: float(x.get("gap") or 0))


def append_auto_graded_pace_play(
    *,
    game_row: dict[str, Any],
    pick: dict[str, Any],
    result: str,
    away_score: int,
    home_score: int,
    store: dict[str, Any] | None = None,
) -> bool:
    """Append one auto-graded Pace play if not already in the official ledger."""
    store = store or load_official_pace()
    day = kickoff_date_et(game_row.get("kickoff"))
    entry: dict[str, Any] = {
        "id": f"pop-auto-{game_row.get('event_id', '')}-{pick.get('kind', '')}",
        "source": "auto_grade",
        "date_et": day.isoformat() if day else None,
        "kickoff": game_row.get("kickoff"),
        "away": game_row.get("away"),
        "home": game_row.get("home"),
        "market": pick.get("kind"),
        "pick": pick.get("pick"),
        "side": pick.get("side"),
        "line": pick.get("line"),
        "price": -110,
        "gap_pts": round(float(pick.get("gap") or 0), 2),
        "result": result,
        "units": _units_at_110(result),
        "espn_away_score": away_score,
        "espn_home_score": home_score,
        "graded_at": datetime.now(timezone.utc).isoformat(),
    }
    slot = _play_slot_key(
        date_et=str(entry.get("date_et") or ""),
        away=str(entry.get("away") or ""),
        home=str(entry.get("home") or ""),
        market=str(entry.get("market") or ""),
    )
    if _slot_already_logged(store, slot):
        return False
    store.setdefault("plays", []).append(entry)
    save_official_pace(store)
    return True


def _format_spread_pick(home: str, away: str, spread_home: float, margin_edge: float) -> str:
    if margin_edge > 0:
        team, line = home, float(spread_home)
    else:
        team, line = away, -float(spread_home)
    sign = "+" if line > 0 else ""
    return f"{team} {sign}{line:g}"


def sync_auto_pace_from_paper_store(paper_store: dict[str, Any] | None = None) -> int:
    """Append auto-graded Pace plays after backfill: Oct 27+ ET, page-display picks only."""
    from sharp_scout.nba.score_model.paper import _game_excluded, _grade_ats_margin, _grade_ou

    paper_store = paper_store or {}
    added = 0
    official = load_official_pace()
    backfill_through = last_official_backfill_date_et(official)
    for g in paper_store.get("games") or []:
        if _game_excluded(g) or not g.get("graded"):
            continue
        day = kickoff_date_et(g.get("kickoff"))
        if day is None:
            continue
        if backfill_through is not None and day <= backfill_through:
            continue
        gr = g["graded"]
        frozen = g.get("frozen") or {}
        snap = frozen.get("snapshot") or (g.get("scans") or [{}])[-1]
        home, away = str(g.get("home") or ""), str(g.get("away") or "")
        primary = frozen.get("pace_display_pick")
        if not primary:
            primary = pace_display_pick_from_snapshot(snap, home=home, away=away)
        if not primary:
            continue
        cs, ct = gr.get("close_spread_home"), gr.get("close_total")
        pm_i = float(
            snap.get("injury_margin") if snap.get("injury_margin") is not None else snap.get("margin") or 0
        )
        pt_i = float(
            snap.get("injury_total") if snap.get("injury_total") is not None else snap.get("total") or 0
        )
        act_total = int(gr["actual_total"])
        act_margin = int(gr["actual_margin"])
        home_score = (act_total + act_margin) // 2
        away_score = (act_total - act_margin) // 2
        if primary["kind"] == "spread" and cs is not None:
            res = _grade_ats_margin(act_margin, cs, min_edge=MIN_AUTO_GAP, proj_margin=pm_i)
        elif primary["kind"] == "total" and ct is not None:
            res = _grade_ou(act_total, ct, min_edge=MIN_AUTO_GAP, proj_total=pt_i)
        else:
            continue
        if res not in ("win", "loss", "push"):
            continue
        game_row = {
            "kickoff": g.get("kickoff"),
            "away": away,
            "home": home,
            "event_id": g.get("event_id"),
        }
        if append_auto_graded_pace_play(
            game_row=game_row,
            pick=primary,
            result=res,
            away_score=away_score,
            home_score=home_score,
            store=official,
        ):
            added += 1
            official = load_official_pace()
    return added
