"""Paper-track score model projections vs market (side-by-side with price-gap plays)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.nba.score_model.engine import V2Engine, p_cover_home, p_over
from sharp_scout.nba.score_model.lines import snapshot_game_lines
from sharp_scout.nba.score_model.state import ensure_score_engine
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import parse_kickoff_utc

logger = logging.getLogger(__name__)

PAPER_PATH = DATA_DIR / "paper" / "nba_score_model.json"
BLEND_W = 0.10


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "games": [], "summary": {}}


def load_paper_store(path: Any = None) -> dict[str, Any]:
    p = path or PAPER_PATH
    if not p.exists():
        return _empty_store()
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return _empty_store()
    raw.setdefault("games", [])
    raw.setdefault("summary", {})
    return raw


def save_paper_store(store: dict[str, Any], path: Any = None) -> None:
    p = path or PAPER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(store, indent=2, default=str) + "\n")


def _find_game(store: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    for g in store["games"]:
        if str(g.get("event_id")) == str(event_id):
            return g
    return None


def _proj_row(engine: V2Engine, ev: dict[str, Any], *, at: str, lines: dict[str, float | None]) -> dict[str, Any]:
    home = normalize_nba_team(str(ev.get("home_team") or ""))
    away = normalize_nba_team(str(ev.get("away_team") or ""))
    kick = parse_kickoff_utc(ev.get("commence_time")) or datetime.now(timezone.utc)
    proj = engine.project(home, away, game_date=kick)
    cs = lines.get("consensus_spread_home")
    ct = lines.get("consensus_total")
    ps = lines.get("pinnacle_spread_home")
    pt = lines.get("pinnacle_total")
    sd_m = float(proj["sd_margin"])
    sd_t = float(proj["sd_total"])
    row: dict[str, Any] = {
        "at": at,
        "home_pts": round(proj["home_pts"], 2),
        "away_pts": round(proj["away_pts"], 2),
        "margin": round(proj["margin"], 2),
        "total": round(proj["total"], 2),
        "lines": lines,
    }
    if cs is not None:
        row["p_cover_home_consensus"] = round(p_cover_home(proj["margin"], float(cs), sd_m), 4)
    if ct is not None:
        row["p_over_consensus"] = round(p_over(proj["total"], float(ct), sd_t), 4)
    if ps is not None:
        row["p_cover_home_pinnacle"] = round(p_cover_home(proj["margin"], float(ps), sd_m), 4)
    if pt is not None:
        row["p_over_pinnacle"] = round(p_over(proj["total"], float(pt), sd_t), 4)
    return row


def record_score_model_scan(
    events: list[dict[str, Any]],
    *,
    engine: V2Engine | None = None,
    store: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append scan projections for each event (reuses scan snapshot — no extra API)."""
    if not events:
        return store or load_paper_store()
    now = now or datetime.now(timezone.utc)
    at = now.isoformat()
    store = store or load_paper_store()
    engine = engine or ensure_score_engine()

    for ev in events:
        eid = str(ev.get("event_id") or "")
        if not eid:
            continue
        home = normalize_nba_team(str(ev.get("home_team") or ""))
        away = normalize_nba_team(str(ev.get("away_team") or ""))
        kick = ev.get("commence_time")
        lines = snapshot_game_lines(ev)
        snap = _proj_row(engine, ev, at=at, lines=lines)

        existing = _find_game(store, eid)
        if existing is None:
            existing = {
                "event_id": eid,
                "home": home,
                "away": away,
                "kickoff": kick.isoformat() if hasattr(kick, "isoformat") else kick,
                "scans": [],
                "frozen": None,
                "graded": None,
            }
            store["games"].append(existing)
        existing["kickoff"] = kick.isoformat() if hasattr(kick, "isoformat") else kick
        existing["scans"].append(snap)
        if len(existing["scans"]) > 40:
            existing["scans"] = existing["scans"][-40:]

    save_paper_store(store)
    return store


def freeze_and_close_lines(store: dict[str, Any], *, now: datetime | None = None) -> int:
    """Lock pre-tip snapshot; attach last scan lines as 'first' reference for CLV."""
    now = now or datetime.now(timezone.utc)
    frozen = 0
    for g in store.get("games") or []:
        if g.get("frozen") or g.get("graded"):
            continue
        kick = parse_kickoff_utc(g.get("kickoff"))
        if kick is None or kick > now:
            continue
        scans = g.get("scans") or []
        if not scans:
            continue
        last = scans[-1]
        g["frozen"] = {
            "frozen_at": now.isoformat(),
            "snapshot": last,
            "first_snapshot": scans[0],
        }
        frozen += 1
    if frozen:
        save_paper_store(store)
    return frozen


def _ats_units(wins: int, losses: int, pushes: int) -> float:
    return wins * (100.0 / 110.0) - losses * 1.0


def _grade_ats_margin(act_margin: float, spread_home: float, *, min_edge: float, proj_margin: float) -> str | None:
    edge = proj_margin + float(spread_home)
    if abs(edge) < min_edge:
        return None
    pick_home = edge > 0
    result_home = act_margin + float(spread_home) > 0
    if act_margin + float(spread_home) == 0:
        return "push"
    return "win" if pick_home == result_home else "loss"


def _grade_ou(act_total: float, close_total: float, *, min_edge: float, proj_total: float) -> str | None:
    edge = proj_total - float(close_total)
    if abs(edge) < min_edge:
        return None
    pick_over = edge > 0
    result_over = act_total > float(close_total)
    if act_total == float(close_total):
        return "push"
    return "win" if pick_over == result_over else "loss"


def grade_score_model_paper(
    scores: list[dict[str, Any]] | None = None,
    *,
    store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from sharp_scout.data.espn_nba import fetch_espn_nba_scores

    store = store or load_paper_store()
    freeze_and_close_lines(store)
    if scores is None:
        try:
            scores = fetch_espn_nba_scores(lookback_days=14)
        except Exception as exc:  # noqa: BLE001
            logger.warning("score paper grade: no scores (%s)", exc)
            scores = []

    index = {f"{normalize_nba_team(r['away_team'])}@{normalize_nba_team(r['home_team'])}": r for r in scores}

    for g in store.get("games") or []:
        if g.get("graded"):
            continue
        key = f"{g['away']}@{g['home']}"
        row = index.get(key)
        if not row:
            continue
        hs, as_ = int(row["home_score"]), int(row["away_score"])
        act_m = hs - as_
        act_t = hs + as_
        frozen = g.get("frozen") or {}
        snap = frozen.get("snapshot") or (g.get("scans") or [{}])[-1]
        first = frozen.get("first_snapshot") or snap
        lines_close = snap.get("lines") or {}
        cs = lines_close.get("consensus_spread_home")
        ct = lines_close.get("consensus_total")
        proj_m = float(snap.get("margin") or 0)
        proj_t = float(snap.get("total") or 0)
        blend_m = proj_m
        blend_t = proj_t
        if cs is not None:
            blend_m = (1 - BLEND_W) * proj_m + BLEND_W * (-float(cs))
        if ct is not None:
            blend_t = (1 - BLEND_W) * proj_t + BLEND_W * float(ct)

        clv_margin = None
        if cs is not None and first.get("lines", {}).get("consensus_spread_home") is not None:
            open_sp = float(first["lines"]["consensus_spread_home"])
            close_sp = float(cs)
            model_edge_open = proj_m + open_sp
            move = close_sp - open_sp
            clv_margin = (move > 0 and model_edge_open > 0) or (move < 0 and model_edge_open < 0)

        g["graded"] = {
            "graded_at": datetime.now(timezone.utc).isoformat(),
            "actual_margin": act_m,
            "actual_total": act_t,
            "close_spread_home": cs,
            "close_total": ct,
            "mae_margin_model": abs(act_m - proj_m),
            "mae_total_model": abs(act_t - proj_t),
            "mae_margin_close": abs(act_m - (-float(cs))) if cs is not None else None,
            "mae_total_close": abs(act_t - float(ct)) if ct is not None else None,
            "mae_margin_blend": abs(act_m - blend_m) if cs is not None else None,
            "mae_total_blend": abs(act_t - blend_t) if ct is not None else None,
            "clv_line_move_toward_model_margin": clv_margin,
        }

    store["summary"] = summarize_score_paper(store)
    save_paper_store(store)
    return store


def summarize_score_paper(store: dict[str, Any]) -> dict[str, Any]:
    graded = [g["graded"] for g in store.get("games") or [] if g.get("graded")]
    if not graded:
        return {"n_graded": 0}

    def mean(key: str) -> float | None:
        vals = [float(g[key]) for g in graded if g.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    ats: dict[str, dict[str, Any]] = {}
    ou: dict[str, dict[str, Any]] = {}
    for thresh in (1.0, 2.0, 3.0):
        mw = ml = mp = 0
        ow = ol = op = 0
        for g in store.get("games") or []:
            gr = g.get("graded")
            if not gr:
                continue
            cs, ct = gr.get("close_spread_home"), gr.get("close_total")
            frozen = g.get("frozen") or {}
            snap = frozen.get("snapshot") or {}
            pm, pt = float(snap.get("margin") or 0), float(snap.get("total") or 0)
            if cs is not None:
                r = _grade_ats_margin(gr["actual_margin"], cs, min_edge=thresh, proj_margin=pm)
                if r == "win":
                    mw += 1
                elif r == "loss":
                    ml += 1
                elif r == "push":
                    mp += 1
            if ct is not None:
                r = _grade_ou(gr["actual_total"], ct, min_edge=thresh, proj_total=pt)
                if r == "win":
                    ow += 1
                elif r == "loss":
                    ol += 1
                elif r == "push":
                    op += 1
        ats[f"ge_{int(thresh)}"] = {
            "wins": mw,
            "losses": ml,
            "pushes": mp,
            "units_at_110": round(_ats_units(mw, ml, mp), 2),
        }
        ou[f"ge_{int(thresh)}"] = {
            "wins": ow,
            "losses": ol,
            "pushes": op,
            "units_at_110": round(_ats_units(ow, ol, op), 2),
        }

    clv_hits = [g["graded"]["clv_line_move_toward_model_margin"] for g in store.get("games") or [] if g.get("graded")]
    clv_n = sum(1 for x in clv_hits if x is not None)
    clv_yes = sum(1 for x in clv_hits if x)

    return {
        "n_graded": len(graded),
        "mae_margin_model": mean("mae_margin_model"),
        "mae_margin_close": mean("mae_margin_close"),
        "mae_margin_blend": mean("mae_margin_blend"),
        "mae_total_model": mean("mae_total_model"),
        "mae_total_close": mean("mae_total_close"),
        "mae_total_blend": mean("mae_total_blend"),
        "ats_vs_close": ats,
        "ou_vs_close": ou,
        "clv_margin_move_toward_model_pct": round(clv_yes / clv_n, 4) if clv_n else None,
        "clv_margin_n": clv_n,
    }


def slate_projections_for_page(store: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Upcoming / open games with latest projection for NBA page."""
    store = store or load_paper_store()
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for g in store.get("games") or []:
        if g.get("graded"):
            continue
        kick = parse_kickoff_utc(g.get("kickoff"))
        if kick and kick < now - timedelta(hours=3):
            continue
        scans = g.get("scans") or []
        if not scans:
            continue
        last = scans[-1]
        out.append(
            {
                "event_id": g.get("event_id"),
                "away": g.get("away"),
                "home": g.get("home"),
                "kickoff": g.get("kickoff"),
                "margin": last.get("margin"),
                "total": last.get("total"),
                "home_pts": last.get("home_pts"),
                "away_pts": last.get("away_pts"),
                "lines": last.get("lines"),
                "frozen": bool(g.get("frozen")),
            }
        )
    out.sort(key=lambda r: r.get("kickoff") or "")
    return out
