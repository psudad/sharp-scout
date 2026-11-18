"""NCAAM morning preview — one daily Odds snapshot, no ledger writes."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.ncaam.preview_store import (
    NCAAM_PREVIEW_DIR,
    PREVIEW_LATEST_PATH,
    preview_already_ran,
    preview_path_for_day,
)
from sharp_scout.data import line_store
from sharp_scout.ncaam.candidates import evaluate_game, pick_best_per_game
from sharp_scout.ncaam.certification_gates import filter_day_picks_for_certification
from sharp_scout.ncaam.credits import (
    CREDITS_PER_ODDS_CALL,
    record_spend,
    should_skip_snapshot,
)
from sharp_scout.ncaam.espn import et_dates_for_runner, fetch_scoreboard_et_day
from sharp_scout.ncaam.lock import LEDGER_PATH, LockWindow, lock_window
from sharp_scout.ncaam.price_edge import filter_day_picks_for_price_edge
from sharp_scout.ncaam.price_edge_diagnostics import record_price_edge_batch
from sharp_scout.ncaam.ratings import ensure_daily_ratings, load_ratings
from sharp_scout.ncaam.rules import apply_daily_cap
from sharp_scout.ncaam.runner import (
    DEMO_ODDS_FIXTURE,
    DEMO_SLATE_FIXTURE,
    NCAAM_LINE_HISTORY_PATH,
    _locked_today,
    fetch_odds_snapshot,
)
from sharp_scout.ncaam.slate import build_slate, load_demo_slate, save_slate
logger = logging.getLogger(__name__)

from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _serialize_pick(play: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    tip = play.get("tip")
    if isinstance(tip, datetime):
        tip_iso = tip.isoformat()
        lead = round((tip - now).total_seconds() / 60.0, 1)
    else:
        tip_iso = str(tip or "")
        lead = play.get("lead_min")
    return {
        "espn_id": play.get("espn_id") or play.get("event_id"),
        "event_id": play.get("event_id") or play.get("espn_id"),
        "away_team": play.get("away_team"),
        "home_team": play.get("home_team"),
        "market": play.get("market"),
        "side": play.get("side"),
        "selection": play.get("selection"),
        "line": play.get("line"),
        "price": play.get("price"),
        "book": play.get("book"),
        "ev": play.get("ev"),
        "units": play.get("units"),
        "tip": tip_iso,
        "lead_min": lead,
        "p_true": play.get("p_true"),
    }


def _write_preview(payload: dict[str, Any], et_day: date) -> None:
    NCAAM_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    preview_path_for_day(et_day).write_text(json.dumps(payload, indent=2, default=str) + "\n")
    PREVIEW_LATEST_PATH.write_text(json.dumps(payload, indent=2, default=str) + "\n")


def run_morning_preview(
    *,
    demo: bool = False,
    now: datetime | None = None,
    force: bool = False,
    manual: bool = False,
    ledger_path: Path | None = None,
    build_site: bool = True,
) -> dict[str, Any]:
    """Evaluate today's full slate once; never append to the official ledger."""
    now = now or datetime.now(timezone.utc)
    ledger_path = ledger_path or LEDGER_PATH
    et_today = now.astimezone(ET).date()

    if not force and preview_already_ran(et_today):
        logger.info("NCAAM morning preview already ran for %s; skipping", et_today)
        return {"skipped": True, "reason": "already_ran_today", "picks": 0}

    ratings_path = ensure_daily_ratings(demo=demo)
    ratings = load_ratings(ratings_path)
    et_days = et_dates_for_runner(now)
    espn_by_day: dict[Any, list[dict[str, Any]]] = {}
    if not demo:
        for d in et_days:
            espn_by_day[d] = fetch_scoreboard_et_day(d)

    skip, reason = should_skip_snapshot(remaining_header=None)
    odds_events: list[dict[str, Any]] = []
    odds_cost: int | None = None
    if demo or not skip:
        odds_events, remaining, cost = fetch_odds_snapshot(demo=demo)
        if not demo and (odds_events or (cost or 0) > 0):
            spent = cost if cost is not None else CREDITS_PER_ODDS_CALL
            odds_cost = int(spent)
            record_spend(spent, remaining_header=remaining)
            logger.info("NCAAM preview odds snapshot cost=%s remaining=%s", spent, remaining)
        if not demo and odds_events:
            line_store.record_snapshot(odds_events, sharp_only=False, path=NCAAM_LINE_HISTORY_PATH)
    elif skip:
        logger.warning("NCAAM preview skipping odds snapshot: %s", reason)
        return {"skipped": True, "reason": reason, "picks": 0}

    demo_shift: timedelta | None = None
    if demo and odds_events:
        first = min(e["commence_time"] for e in odds_events if isinstance(e.get("commence_time"), datetime))
        demo_shift = (now + timedelta(minutes=60)) - first
        for e in odds_events:
            if isinstance(e.get("commence_time"), datetime):
                e["commence_time"] = e["commence_time"] + demo_shift

    all_slate: list[dict[str, Any]] = []
    for d in et_days:
        if demo and DEMO_SLATE_FIXTURE.exists():
            slate = load_demo_slate(DEMO_SLATE_FIXTURE)
            if demo_shift is not None:
                for r in slate:
                    if isinstance(r.get("commence_time"), datetime):
                        r["commence_time"] = r["commence_time"] + demo_shift
        else:
            espn = espn_by_day.get(d) or []
            slate = build_slate(et_day=d, odds_events=odds_events, espn_rows=espn)
            if not demo:
                save_slate(slate, et_day=d)
        all_slate.extend(slate)

    odds_by_id = {str(e.get("event_id")): e for e in odds_events}
    candidates: list[dict[str, Any]] = []
    for game in all_slate:
        tip = game.get("commence_time")
        if not isinstance(tip, datetime):
            continue
        if lock_window(now, tip) == LockWindow.POST_TIP:
            continue
        if tip.astimezone(ET).date() != et_today:
            continue
        oid = game.get("odds_event_id")
        ev = odds_by_id.get(str(oid)) if oid else None
        if (
            ev
            and not demo
            and ev.get("home_team")
            and ev.get("away_team")
            and (ev.get("home_team"), ev.get("away_team")) != (game.get("home_team"), game.get("away_team"))
        ):
            ev = None
        if not ev and demo:
            ev = odds_events[0] if odds_events else None
        if not ev:
            continue
        for c in evaluate_game(game, ev, ratings, now=now):
            c["et_day"] = tip.astimezone(ET).date().isoformat()
            candidates.append(c)

    best = pick_best_per_game(candidates)
    done_n, done_u = _locked_today(ledger_path, et_today.isoformat())
    day_picks = apply_daily_cap(
        list(best.values()),
        et_day=et_today,
        already_plays=done_n,
        already_units=done_u,
    )

    settings = get_settings()
    min_edge = float(settings.ncaam_price_edge_min)
    gate_on = bool(settings.ncaam_price_edge_gate_enabled)
    day_picks, diag_rows = filter_day_picks_for_price_edge(
        day_picks, gate_enabled=gate_on, min_edge=min_edge
    )
    if diag_rows:
        record_price_edge_batch(diag_rows, gate_enabled=gate_on, min_edge=min_edge)

    day_picks, _cert_blocked = filter_day_picks_for_certification(day_picks)

    picks = [_serialize_pick(p, now=now) for p in day_picks]
    payload = {
        "generated_at": now.isoformat(),
        "et_day": et_today.isoformat(),
        "manual": manual or force,
        "odds_cost": odds_cost if odds_cost is not None else (0 if demo else CREDITS_PER_ODDS_CALL),
        "picks": picks,
        "candidates_n": len(candidates),
    }
    _write_preview(payload, et_today)

    if build_site:
        from sharp_scout.site.ncaam_page import build_ncaam_page

        if demo:
            build_ncaam_page(ledger_path=ledger_path)
        else:
            build_ncaam_page()

    return {
        "skipped": False,
        "picks": len(picks),
        "candidates": len(candidates),
        "odds_cost": payload["odds_cost"],
    }