"""Paper-track score model projections vs market (side-by-side with price-gap plays)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sharp_scout.config import DATA_DIR, get_settings
from sharp_scout.nba.score_model.engine import V2Engine, p_cover_home, p_over
from sharp_scout.nba.score_model.lines import snapshot_game_lines
from sharp_scout.nba.score_model.state import ensure_score_engine
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import kickoff_in_horizon, parse_kickoff_utc

logger = logging.getLogger(__name__)

PAPER_PATH = DATA_DIR / "paper" / "nba_score_model.json"
BLEND_W = 0.10
_BLOCKED_EVENT_IDS = frozenset({"test", "demo"})


def is_live_paper_event_id(event_id: Any) -> bool:
    """Reject demo/test ids from live NBA score-model paper tracking."""
    eid = str(event_id or "").strip().lower()
    if not eid or eid in _BLOCKED_EVENT_IDS or eid.startswith("demo-"):
        return False
    if eid.isdigit() and len(eid) >= 8:
        return True
    return len(eid) >= 10


def _scrub_test_games(store: dict[str, Any]) -> None:
    before = len(store.get("games") or [])
    store["games"] = [g for g in store.get("games") or [] if is_live_paper_event_id(g.get("event_id"))]
    if len(store["games"]) < before:
        logger.info("score paper: dropped %d non-live event id(s)", before - len(store["games"]))


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
    _scrub_test_games(raw)
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


def _event_id_is_espn(event_id: Any) -> bool:
    eid = str(event_id or "").strip()
    return eid.isdigit()


def _projection_row_has_lines(row: dict[str, Any]) -> bool:
    lines = row.get("lines") or {}
    return lines.get("consensus_spread_home") is not None or lines.get("consensus_total") is not None


def _odds_api_projection_priority(row: dict[str, Any]) -> int:
    """Higher = prefer this row for market lines and Odds API tip time."""
    score = 0
    if _projection_row_has_lines(row):
        score += 2
    if not _event_id_is_espn(row.get("event_id")):
        score += 1
    return score


def merge_slate_projection_rows(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """One row per ET matchup: market lines + Odds API kickoff when available."""
    primary = a if _odds_api_projection_priority(a) >= _odds_api_projection_priority(b) else b
    secondary = b if primary is a else a
    merged = dict(primary)
    if _projection_row_has_lines(primary):
        pass
    elif _projection_row_has_lines(secondary):
        merged["lines"] = secondary.get("lines")
        for key in (
            "margin",
            "total",
            "injury_margin",
            "injury_total",
            "home_pts",
            "away_pts",
            "injury_home_pts",
            "injury_away_pts",
            "home_absences",
            "away_absences",
            "home_excluded",
            "away_excluded",
            "injury_news_after_line",
        ):
            if secondary.get(key) is not None:
                merged[key] = secondary[key]
    if not _event_id_is_espn(secondary.get("event_id")) and _event_id_is_espn(primary.get("event_id")):
        merged["kickoff"] = secondary.get("kickoff")
        merged["event_id"] = secondary.get("event_id")
    return merged


def dedupe_slate_projection_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from sharp_scout.nba.slate_et import kickoff_date_et

    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        day = kickoff_date_et(row.get("kickoff"))
        if day is None:
            continue
        away = normalize_nba_team(str(row.get("away") or ""))
        home = normalize_nba_team(str(row.get("home") or ""))
        key = (day.isoformat(), away, home)
        prev = buckets.get(key)
        buckets[key] = merge_slate_projection_rows(prev, row) if prev else row
    out = sorted(buckets.values(), key=lambda r: r.get("kickoff") or "")
    return out


def _find_game_by_matchup(
    store: dict[str, Any],
    away: str,
    home: str,
    *,
    kickoff: Any = None,
) -> dict[str, Any] | None:
    from sharp_scout.nba.slate_et import kickoff_date_et

    target_day = kickoff_date_et(kickoff) if kickoff else None
    for g in store.get("games") or []:
        if g.get("away") != away or g.get("home") != home:
            continue
        if target_day is None:
            return g
        if kickoff_date_et(g.get("kickoff")) == target_day:
            return g
    return None


def _game_excluded(g: dict[str, Any]) -> bool:
    return bool(g.get("excluded")) or g.get("exclude_reason") == "kickoff_outside_horizon"


def _first_scan_at(g: dict[str, Any]) -> datetime | None:
    scans = g.get("scans") or []
    if not scans:
        return None
    return parse_kickoff_utc(scans[0].get("at"))


def void_score_paper_outside_horizon(
    store: dict[str, Any],
    *,
    horizon_hours: float | None = None,
    now: datetime | None = None,
) -> int:
    """Void score-model games logged outside nba_prop_horizon_hours (same rules as ledger)."""
    settings = get_settings()
    hours = horizon_hours if horizon_hours is not None else settings.nba_prop_horizon_hours
    now = now or datetime.now(timezone.utc)
    changed = 0
    for g in store.get("games") or []:
        if g.get("graded"):
            continue
        created = _first_scan_at(g) or parse_kickoff_utc(g.get("kickoff"))
        kick = parse_kickoff_utc(g.get("kickoff"))
        if kick is None or created is None:
            continue
        outside = kick > created + timedelta(hours=hours + 1) or not kickoff_in_horizon(
            g.get("kickoff"), hours, now=created
        )
        if not outside and _game_excluded(g):
            g.pop("excluded", None)
            g.pop("exclude_reason", None)
            g.pop("voided_at", None)
            changed += 1
            continue
        if outside and not _game_excluded(g):
            g["excluded"] = True
            g["exclude_reason"] = "kickoff_outside_horizon"
            g["voided_at"] = now.isoformat()
            changed += 1
    if changed:
        store["summary"] = summarize_score_paper(store)
    return changed


def _proj_row(
    engine: V2Engine,
    ev: dict[str, Any],
    *,
    at: str,
    lines: dict[str, float | None],
    prior_status: dict[str, str] | None = None,
    injury_store: dict[str, Any] | None = None,
    first_scan_at: str | None = None,
) -> dict[str, Any]:
    from sharp_scout.nba.score_model.injury_adjust import (
        apply_injury_to_projection,
        injury_news_after_first_line,
    )

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
    inj = apply_injury_to_projection(proj, home, away, prior_status=prior_status)
    row: dict[str, Any] = {
        "at": at,
        "home_pts": round(proj["home_pts"], 2),
        "away_pts": round(proj["away_pts"], 2),
        "margin": round(proj["margin"], 2),
        "total": round(proj["total"], 2),
        "injury_home_pts": inj.get("injury_home_pts"),
        "injury_away_pts": inj.get("injury_away_pts"),
        "injury_margin": inj.get("injury_margin"),
        "injury_total": inj.get("injury_total"),
        "home_absences": inj.get("home_absences") or [],
        "away_absences": inj.get("away_absences") or [],
        "home_excluded": inj.get("home_excluded") or [],
        "away_excluded": inj.get("away_excluded") or [],
        "lines": lines,
    }
    absences = (row["home_absences"] or []) + (row["away_absences"] or [])
    row["injury_news_after_line"] = injury_news_after_first_line(
        first_scan_at=first_scan_at or at,
        absences=[a for a in absences if a.get("kind") != "return"],
        injury_store=injury_store,
    )
    if cs is not None:
        row["p_cover_home_consensus"] = round(p_cover_home(proj["margin"], float(cs), sd_m), 4)
        row["p_cover_home_consensus_injury"] = round(
            p_cover_home(float(inj["injury_margin"]), float(cs), sd_m), 4
        )
    if ct is not None:
        row["p_over_consensus"] = round(p_over(proj["total"], float(ct), sd_t), 4)
        row["p_over_consensus_injury"] = round(p_over(float(inj["injury_total"]), float(ct), sd_t), 4)
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
    horizon_hours: float | None = None,
) -> dict[str, Any]:
    """Append scan projections for each event (reuses scan snapshot — no extra API)."""
    now = now or datetime.now(timezone.utc)
    at = now.isoformat()
    store = store or load_paper_store()
    settings = get_settings()
    hours = horizon_hours if horizon_hours is not None else settings.nba_prop_horizon_hours
    void_score_paper_outside_horizon(store, horizon_hours=hours, now=now)
    if not events:
        save_paper_store(store)
        return store
    engine = engine or ensure_score_engine()
    shadow_engine = None
    try:
        from sharp_scout.nba.score_model.shadow_v2_proj import shadow_v2_enabled
        from sharp_scout.nba.score_model.state_v2 import ensure_shadow_score_engine

        if shadow_v2_enabled():
            shadow_engine = ensure_shadow_score_engine()
    except Exception:  # noqa: BLE001
        shadow_engine = None
    try:
        from sharp_scout.nba.score_model.injury_lag import load_store as load_injury_store

        injury_store = load_injury_store()
        prior_status = dict(injury_store.get("player_status") or {})
    except Exception:  # noqa: BLE001
        injury_store = {}
        prior_status = {}

    for ev in events:
        if not kickoff_in_horizon(ev.get("commence_time"), hours, now=now):
            continue
        eid = str(ev.get("event_id") or "")
        if not eid or not is_live_paper_event_id(eid):
            continue
        home = normalize_nba_team(str(ev.get("home_team") or ""))
        away = normalize_nba_team(str(ev.get("away_team") or ""))
        kick = ev.get("commence_time")
        lines = snapshot_game_lines(ev)
        existing = _find_game_by_matchup(store, away, home, kickoff=kick) or _find_game(store, eid)
        first_scan_at = (existing.get("scans") or [{}])[0].get("at") if existing else None
        snap = _proj_row(
            engine,
            ev,
            at=at,
            lines=lines,
            prior_status=prior_status,
            injury_store=injury_store,
            first_scan_at=first_scan_at,
        )
        kick_dt = parse_kickoff_utc(kick)
        snap["after_tip"] = bool(kick_dt and now > kick_dt)
        from sharp_scout.nba.score_model.pace_v1 import pace_display_pick_from_snapshot

        v1_pick = pace_display_pick_from_snapshot(snap, home=home, away=away, engine=engine)
        if v1_pick:
            from sharp_scout.nba.score_model.pace_v1 import recommended_unit_fraction

            snap["pace_v1_pick"] = v1_pick.get("pick")
            snap["pace_v1_gap"] = v1_pick.get("gap")
            snap["pace_v1_recommended_units"] = recommended_unit_fraction(
                snap, v1_pick, home=home, away=away, engine=engine
            )
        if shadow_engine is not None:
            from sharp_scout.nba.score_model.shadow_v2_proj import shadow_v2_proj_row

            snap["shadow_v2"] = shadow_v2_proj_row(
                shadow_engine,
                ev,
                at=at,
                lines=lines,
                prior_status=prior_status,
                injury_store=injury_store,
                first_scan_at=first_scan_at,
            )
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
        else:
            existing["event_id"] = eid
        existing["kickoff"] = kick.isoformat() if hasattr(kick, "isoformat") else kick
        existing["home"] = home
        existing["away"] = away
        existing["scans"].append(snap)
        if len(existing["scans"]) > 40:
            existing["scans"] = existing["scans"][-40:]
        if v1_pick and not snap.get("after_tip"):
            existing["pace_published_pick"] = v1_pick
        if kick_dt and not snap.get("after_tip"):
            from sharp_scout.nba.score_model.totals_shadow import maybe_record_totals_shadow_for_scan

            maybe_record_totals_shadow_for_scan(
                engine,
                event_id=eid,
                home=home,
                away=away,
                kickoff=kick_dt,
                scan_at=at,
                snap=snap,
            )

    save_paper_store(store)
    return store


def _merged_lines_from_scans(scans: list[dict[str, Any]]) -> dict[str, float | None]:
    lines: dict[str, float | None] = {}
    for snap in scans:
        blob = snap.get("lines") or {}
        for key in ("consensus_spread_home", "consensus_total", "pinnacle_spread_home", "pinnacle_total"):
            if blob.get(key) is not None:
                lines[key] = blob.get(key)
    return lines


def _tip_snapshot(
    g: dict[str, Any],
    *,
    engine: V2Engine,
    now: datetime,
) -> dict[str, Any]:
    """Last scan merged with best available market lines; re-project at tip when possible."""
    scans = g.get("scans") or []
    if not scans:
        return {}
    base = dict(scans[-1])
    merged_lines = _merged_lines_from_scans(scans)
    if merged_lines:
        base["lines"] = merged_lines
    home = str(g.get("home") or "")
    away = str(g.get("away") or "")
    kick = parse_kickoff_utc(g.get("kickoff")) or now
    ev = {
        "event_id": g.get("event_id"),
        "home_team": home,
        "away_team": away,
        "commence_time": kick,
    }
    try:
        from sharp_scout.nba.score_model.injury_lag import load_store as load_injury_store

        injury_store = load_injury_store()
        prior_status = dict(injury_store.get("player_status") or {})
    except Exception:  # noqa: BLE001
        injury_store = {}
        prior_status = {}
    first_scan_at = scans[0].get("at")
    fresh = _proj_row(
        engine,
        ev,
        at=now.isoformat(),
        lines=merged_lines,
        prior_status=prior_status,
        injury_store=injury_store,
        first_scan_at=first_scan_at,
    )
    fresh["source"] = "tip_freeze"
    for key in (
        "home_pts",
        "away_pts",
        "margin",
        "total",
        "injury_home_pts",
        "injury_away_pts",
        "injury_margin",
        "injury_total",
        "home_absences",
        "away_absences",
        "home_excluded",
        "away_excluded",
        "injury_news_after_line",
        "large_gap_warning",
        "market_gap_margin",
        "p_cover_home_consensus",
        "p_cover_home_consensus_injury",
        "p_over_consensus",
        "p_over_consensus_injury",
    ):
        if fresh.get(key) is not None:
            base[key] = fresh[key]
    return base


def freeze_and_close_lines(store: dict[str, Any], *, now: datetime | None = None) -> int:
    """Lock one tip-time snapshot (merged pre-tip lines + v1 pick; shadow v2 sidecar)."""
    now = now or datetime.now(timezone.utc)
    frozen = 0
    from sharp_scout.nba.score_model.official_pace import pace_display_pick_from_snapshot

    for g in store.get("games") or []:
        if _game_excluded(g) or g.get("frozen") or g.get("graded"):
            continue
        kick = parse_kickoff_utc(g.get("kickoff"))
        if kick is None or kick > now:
            continue
        scans = g.get("scans") or []
        if not scans:
            continue
        pre_tip = [s for s in scans if not s.get("after_tip")] or scans
        last = dict(pre_tip[-1])
        merged = _merged_lines_from_scans(pre_tip)
        if merged:
            last["lines"] = merged
        home = str(g.get("home") or "")
        away = str(g.get("away") or "")
        display_pick = pace_display_pick_from_snapshot(last, home=home, away=away)
        g["frozen"] = {
            "frozen_at": now.isoformat(),
            "snapshot": last,
            "first_snapshot": scans[0],
            "pace_display_pick": display_pick,
            "pace_published_pick": g.get("pace_published_pick"),
            "shadow_v2": last.get("shadow_v2"),
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


def dedupe_paper_games_by_matchup(store: dict[str, Any]) -> int:
    """Keep one row per ET away@home (prefer Odds API id + market lines + most scans)."""
    from sharp_scout.nba.slate_et import kickoff_date_et

    def score(g: dict[str, Any]) -> tuple[int, int, int]:
        eid = str(g.get("event_id") or "")
        espn = 1 if eid.isdigit() and len(eid) >= 8 else 0
        scans = g.get("scans") or []
        lines = 1 if any((s.get("lines") or {}).get("consensus_spread_home") is not None for s in scans) else 0
        return (lines, espn, len(scans))

    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for g in store.get("games") or []:
        day = kickoff_date_et(g.get("kickoff"))
        if day is None:
            continue
        key = (day.isoformat(), str(g.get("away")), str(g.get("home")))
        prev = buckets.get(key)
        if prev is None or score(g) > score(prev):
            buckets[key] = g
    before = len(store.get("games") or [])
    store["games"] = list(buckets.values())
    return before - len(store["games"])


def grade_score_model_paper(
    scores: list[dict[str, Any]] | None = None,
    *,
    store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from sharp_scout.data.espn_nba import fetch_espn_nba_scores

    store = store or load_paper_store()
    void_score_paper_outside_horizon(store)
    dedupe_paper_games_by_matchup(store)
    freeze_and_close_lines(store)
    if scores is None:
        try:
            scores = fetch_espn_nba_scores(lookback_days=14)
        except Exception as exc:  # noqa: BLE001
            logger.warning("score paper grade: no scores (%s)", exc)
            scores = []

    index = {f"{normalize_nba_team(r['away_team'])}@{normalize_nba_team(r['home_team'])}": r for r in scores}

    for g in store.get("games") or []:
        if _game_excluded(g) or g.get("graded"):
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
        inj_m = float(snap.get("injury_margin") if snap.get("injury_margin") is not None else proj_m)
        inj_t = float(snap.get("injury_total") if snap.get("injury_total") is not None else proj_t)
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
            "mae_margin_injury": abs(act_m - inj_m),
            "mae_total_injury": abs(act_t - inj_t),
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
    active = [g for g in store.get("games") or [] if not _game_excluded(g)]
    graded = [g["graded"] for g in active if g.get("graded")]
    if not graded:
        return {"n_graded": 0}

    def mean(key: str) -> float | None:
        vals = [float(g[key]) for g in graded if g.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    ats: dict[str, dict[str, Any]] = {}
    ou: dict[str, dict[str, Any]] = {}
    ats_inj: dict[str, dict[str, Any]] = {}
    ou_inj: dict[str, dict[str, Any]] = {}
    for thresh in (1.0, 2.0, 3.0):
        mw = ml = mp = 0
        ow = ol = op = 0
        mw_i = ml_i = mp_i = 0
        ow_i = ol_i = op_i = 0
        for g in active:
            gr = g.get("graded")
            if not gr:
                continue
            cs, ct = gr.get("close_spread_home"), gr.get("close_total")
            frozen = g.get("frozen") or {}
            snap = frozen.get("snapshot") or {}
            pm, pt = float(snap.get("margin") or 0), float(snap.get("total") or 0)
            pm_i = float(snap.get("injury_margin") if snap.get("injury_margin") is not None else pm)
            pt_i = float(snap.get("injury_total") if snap.get("injury_total") is not None else pt)
            if cs is not None:
                r = _grade_ats_margin(gr["actual_margin"], cs, min_edge=thresh, proj_margin=pm)
                if r == "win":
                    mw += 1
                elif r == "loss":
                    ml += 1
                elif r == "push":
                    mp += 1
                ri = _grade_ats_margin(gr["actual_margin"], cs, min_edge=thresh, proj_margin=pm_i)
                if ri == "win":
                    mw_i += 1
                elif ri == "loss":
                    ml_i += 1
                elif ri == "push":
                    mp_i += 1
            if ct is not None:
                r = _grade_ou(gr["actual_total"], ct, min_edge=thresh, proj_total=pt)
                if r == "win":
                    ow += 1
                elif r == "loss":
                    ol += 1
                elif r == "push":
                    op += 1
                ri = _grade_ou(gr["actual_total"], ct, min_edge=thresh, proj_total=pt_i)
                if ri == "win":
                    ow_i += 1
                elif ri == "loss":
                    ol_i += 1
                elif ri == "push":
                    op_i += 1
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
        ats_inj[f"ge_{int(thresh)}"] = {
            "wins": mw_i,
            "losses": ml_i,
            "pushes": mp_i,
            "units_at_110": round(_ats_units(mw_i, ml_i, mp_i), 2),
        }
        ou_inj[f"ge_{int(thresh)}"] = {
            "wins": ow_i,
            "losses": ol_i,
            "pushes": op_i,
            "units_at_110": round(_ats_units(ow_i, ol_i, op_i), 2),
        }

    clv_hits = [g["graded"]["clv_line_move_toward_model_margin"] for g in active if g.get("graded")]
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
        "ats_vs_close_injury": ats_inj,
        "ou_vs_close_injury": ou_inj,
        "mae_margin_injury": mean("mae_margin_injury"),
        "mae_total_injury": mean("mae_total_injury"),
        "clv_margin_move_toward_model_pct": round(clv_yes / clv_n, 4) if clv_n else None,
        "clv_margin_n": clv_n,
    }


def slate_projections_for_page(store: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Upcoming / open games with latest projection for NBA page."""
    from sharp_scout.nba.slate_et import kickoff_date_et
    from sharp_scout.utils.slate import ET

    store = store or load_paper_store()
    now = datetime.now(timezone.utc)
    today_et = now.astimezone(ET).date()
    out: list[dict[str, Any]] = []
    for g in store.get("games") or []:
        if _game_excluded(g) or g.get("graded"):
            continue
        kick = parse_kickoff_utc(g.get("kickoff"))
        if kick and kick < now - timedelta(minutes=15):
            continue
        day = kickoff_date_et(g.get("kickoff"))
        if day is not None and day < today_et:
            continue
        scans = g.get("scans") or []
        if not scans:
            continue
        last = scans[-1]
        first_at = (g.get("scans") or [{}])[0].get("at")
        out.append(
            {
                "event_id": g.get("event_id"),
                "away": g.get("away"),
                "home": g.get("home"),
                "kickoff": g.get("kickoff"),
                "margin": last.get("margin"),
                "total": last.get("total"),
                "injury_margin": last.get("injury_margin"),
                "injury_total": last.get("injury_total"),
                "home_pts": last.get("home_pts"),
                "away_pts": last.get("away_pts"),
                "injury_home_pts": last.get("injury_home_pts"),
                "injury_away_pts": last.get("injury_away_pts"),
                "home_absences": last.get("home_absences") or [],
                "away_absences": last.get("away_absences") or [],
                "home_excluded": last.get("home_excluded") or [],
                "away_excluded": last.get("away_excluded") or [],
                "injury_news_after_line": last.get("injury_news_after_line"),
                "first_scan_at": first_at,
                "lines": last.get("lines"),
                "frozen": bool(g.get("frozen")),
            }
        )
    return dedupe_slate_projection_rows(out)


def refresh_espn_slate_injury_scans(
    *,
    engine: V2Engine | None = None,
    store: dict[str, Any] | None = None,
    now: datetime | None = None,
    horizon_hours: float | None = None,
) -> int:
    """ESPN slate (ET game dates) — upsert projections + injury fields without Odds API."""
    from sharp_scout.data.espn_nba import fetch_espn_nba_upcoming
    from sharp_scout.nba.slate_et import espn_events_for_injury_window

    settings = get_settings()
    hours = horizon_hours if horizon_hours is not None else settings.nba_prop_horizon_hours
    now = now or datetime.now(timezone.utc)
    at = now.isoformat()
    store = store or load_paper_store()
    engine = engine or ensure_score_engine()
    try:
        from sharp_scout.nba.score_model.injury_lag import load_store as load_injury_store

        injury_store = load_injury_store()
        prior_status = dict(injury_store.get("player_status") or {})
    except Exception:  # noqa: BLE001
        injury_store = {}
        prior_status = {}

    slate = espn_events_for_injury_window(
        fetch_espn_nba_upcoming(days_ahead=2),
        now=now,
        horizon_hours=hours,
    )
    updated = 0
    for ev in slate:
        home = normalize_nba_team(str(ev.get("home_team") or ""))
        away = normalize_nba_team(str(ev.get("away_team") or ""))
        kick = ev.get("kickoff")
        eid = str(ev.get("event_id") or "")
        if not home or not away or not eid:
            continue

        existing = _find_game_by_matchup(store, away, home, kickoff=kick) or _find_game(store, eid)
        lines: dict[str, float | None] = {}
        if existing:
            scans = existing.get("scans") or []
            if scans:
                lines = dict(scans[-1].get("lines") or {})
            eid = str(existing.get("event_id") or eid)
        else:
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
        existing["home"] = home
        existing["away"] = away
        scans = existing.get("scans") or []
        first_scan_at = scans[0].get("at") if scans else None
        ev_row = {
            "event_id": eid,
            "home_team": home,
            "away_team": away,
            "commence_time": kick,
        }
        snap = _proj_row(
            engine,
            ev_row,
            at=at,
            lines=lines,
            prior_status=prior_status,
            injury_store=injury_store,
            first_scan_at=first_scan_at,
        )
        snap["source"] = "injury_refresh"
        existing["scans"].append(snap)
        if len(existing["scans"]) > 40:
            existing["scans"] = existing["scans"][-40:]
        kick_dt = parse_kickoff_utc(kick)
        if kick_dt:
            from sharp_scout.nba.score_model.totals_shadow import maybe_record_totals_shadow_for_scan

            maybe_record_totals_shadow_for_scan(
                engine,
                event_id=eid,
                home=home,
                away=away,
                kickoff=kick_dt,
                scan_at=at,
                snap=snap,
            )
        updated += 1

    if updated:
        save_paper_store(store)
    return updated


def refresh_open_game_injury_scans(
    *,
    engine: V2Engine | None = None,
    store: dict[str, Any] | None = None,
    now: datetime | None = None,
    horizon_hours: float | None = None,
) -> int:
    """Backward-compatible alias for ESPN ET slate injury refresh."""
    return refresh_espn_slate_injury_scans(
        engine=engine,
        store=store,
        now=now,
        horizon_hours=horizon_hours,
    )
