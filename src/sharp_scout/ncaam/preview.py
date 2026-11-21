"""NCAAM likely-play preview — reuses runner Odds snapshots; never touches the ledger."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.config import get_settings
from sharp_scout.copy.explain import format_display_datetime_et
from sharp_scout.ncaam.candidates import evaluate_game, pick_best_per_game
from sharp_scout.ncaam.certification_gates import filter_day_picks_for_certification
from sharp_scout.ncaam.lock import LEDGER_PATH, LockWindow, lock_window
from sharp_scout.ncaam.price_edge import filter_day_picks_for_price_edge
from sharp_scout.ncaam.preview_store import (
    NCAAM_PREVIEW_DIR,
    PREVIEW_LATEST_PATH,
    load_preview,
    preview_path_for_day,
)
from sharp_scout.ncaam.rules import apply_daily_cap

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
PREVIEW_STATE_ACTIVE = "active"
PREVIEW_STATE_DROPPED = "no_longer_qualifies"


def _et_display(now: datetime) -> str:
    return format_display_datetime_et(now.isoformat())


def _pick_id(play: dict[str, Any]) -> str:
    return str(play.get("espn_id") or play.get("event_id") or "")


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


def _preview_eligible(now: datetime, tip: datetime) -> bool:
    return lock_window(now, tip) == LockWindow.TOO_EARLY


def _qualifying_preview_picks(
    all_slate: list[dict[str, Any]],
    odds_by_id: dict[str, dict[str, Any]],
    ratings: dict[str, dict[str, float]],
    *,
    now: datetime,
    ledger_path: Path,
    demo: bool,
) -> tuple[list[dict[str, Any]], set[str]]:
    from sharp_scout.ncaam.runner import _locked_today

    et_today = now.astimezone(ET).date()
    candidates: list[dict[str, Any]] = []
    considered_ids: set[str] = set()
    odds_events_stub: list[dict[str, Any]] = list(odds_by_id.values())
    for game in all_slate:
        tip = game.get("commence_time")
        if not isinstance(tip, datetime):
            continue
        if not _preview_eligible(now, tip):
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
        if not ev and demo and odds_events_stub:
            ev = odds_events_stub[0]
        if not ev:
            continue
        eid = str(game.get("espn_id") or game.get("event_id") or "")
        if eid:
            considered_ids.add(eid)
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
    day_picks, _diag_rows = filter_day_picks_for_price_edge(
        day_picks, gate_enabled=gate_on, min_edge=min_edge
    )
    day_picks, _cert_blocked = filter_day_picks_for_certification(day_picks)
    return day_picks, considered_ids


def merge_preview_picks(
    existing: list[dict[str, Any]],
    fresh_models: list[dict[str, Any]],
    *,
    now: datetime,
    considered_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Keep prior rows; refresh active picks; mark gate drops; never delete.

    A still-TOO_EARLY pick is marked no_longer_qualifies only when that game was
    in this pass's snapshot/evaluation set (`considered_ids`) and did not qualify.
    Absence from a later 0-candidate or partial snapshot is not a drop.
    """
    et_now = _et_display(now)
    fresh_serialized = [_serialize_pick(p, now=now) for p in fresh_models]
    for row in fresh_serialized:
        row["preview_state"] = PREVIEW_STATE_ACTIVE

    fresh_by_id = {_pick_id(row): row for row in fresh_serialized}
    prior_by_id = {_pick_id(row): row for row in existing if _pick_id(row)}
    considered = {str(i) for i in (considered_ids or set()) if str(i)}

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pid, row in fresh_by_id.items():
        seen.add(pid)
        prev = prior_by_id.get(pid)
        row["updated_at_et"] = et_now
        row["added_at_et"] = (prev or {}).get("added_at_et") or (prev or {}).get("updated_at_et") or et_now
        merged.append(row)

    for pid, prev in prior_by_id.items():
        if pid in seen:
            continue
        row = dict(prev)
        tip_raw = row.get("tip")
        try:
            tip = datetime.fromisoformat(str(tip_raw).replace("Z", "+00:00"))
        except ValueError:
            tip = None
        # Only drop if this game was evaluated this pass and failed to qualify.
        if tip and _preview_eligible(now, tip) and pid in considered:
            if row.get("preview_state") != PREVIEW_STATE_DROPPED:
                row["preview_state"] = PREVIEW_STATE_DROPPED
                row["updated_at_et"] = et_now
        merged.append(row)

    def _sort_key(item: dict[str, Any]) -> tuple:
        active = 0 if item.get("preview_state") == PREVIEW_STATE_ACTIVE else 1
        return (active, str(item.get("tip") or ""))

    merged.sort(key=_sort_key)
    return merged


def _write_preview(payload: dict[str, Any], et_day: date) -> None:
    NCAAM_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    preview_path_for_day(et_day).write_text(json.dumps(payload, indent=2, default=str) + "\n")
    PREVIEW_LATEST_PATH.write_text(json.dumps(payload, indent=2, default=str) + "\n")


def refresh_preview_from_snapshot(
    odds_events: list[dict[str, Any]],
    all_slate: list[dict[str, Any]],
    *,
    ratings: dict[str, dict[str, float]],
    now: datetime | None = None,
    ledger_path: Path | None = None,
    demo: bool = False,
    build_site: bool = False,
) -> dict[str, Any]:
    """Merge likely plays from an existing odds snapshot (no Odds API calls)."""
    if not odds_events:
        return {"skipped": True, "reason": "no_odds_events", "picks": 0}

    now = now or datetime.now(timezone.utc)
    ledger_path = ledger_path or LEDGER_PATH
    et_today = now.astimezone(ET).date()
    odds_by_id = {str(e.get("event_id")): e for e in odds_events}

    fresh_models, considered_ids = _qualifying_preview_picks(
        all_slate, odds_by_id, ratings, now=now, ledger_path=ledger_path, demo=demo
    )
    existing_doc = load_preview(et_day=et_today)
    existing_rows = list(existing_doc.get("picks") or [])
    merged = merge_preview_picks(
        existing_rows, fresh_models, now=now, considered_ids=considered_ids
    )
    active_n = sum(1 for p in merged if p.get("preview_state") == PREVIEW_STATE_ACTIVE)

    payload = {
        "generated_at": now.isoformat(),
        "et_day": et_today.isoformat(),
        "last_scan_at_et": _et_display(now),
        "picks": merged,
        "active_n": active_n,
        "candidates_n": len(fresh_models),
    }
    _write_preview(payload, et_today)

    if build_site:
        from sharp_scout.site.ncaam_page import build_ncaam_page

        if demo:
            build_ncaam_page(ledger_path=ledger_path)
        else:
            build_ncaam_page()

    logger.info(
        "NCAAM preview refresh: active=%s total_rows=%s (no extra Odds API)",
        active_n,
        len(merged),
    )
    return {
        "skipped": False,
        "picks": active_n,
        "rows": len(merged),
        "candidates": len(fresh_models),
        "odds_cost": 0,
    }


def run_morning_preview(
    *,
    demo: bool = False,
    now: datetime | None = None,
    force: bool = False,
    manual: bool = False,
    ledger_path: Path | None = None,
    build_site: bool = True,
) -> dict[str, Any]:
    """Demo/offline preview exercise, or rebuild the board from existing preview JSON (live)."""
    now = now or datetime.now(timezone.utc)
    ledger_path = ledger_path or LEDGER_PATH

    if not demo:
        if build_site:
            from sharp_scout.site.ncaam_page import build_ncaam_page

            build_ncaam_page()
        doc = load_preview(et_day=now.astimezone(ET).date())
        return {
            "skipped": False,
            "picks": int(doc.get("active_n") or 0),
            "rebuild_only": True,
            "odds_cost": 0,
        }

    from sharp_scout.ncaam.espn import et_dates_for_runner
    from sharp_scout.ncaam.ratings import ensure_daily_ratings, load_ratings
    from sharp_scout.ncaam.runner import (
        DEMO_ODDS_FIXTURE,
        DEMO_SLATE_FIXTURE,
        fetch_odds_snapshot,
    )
    from sharp_scout.ncaam.slate import build_slate, load_demo_slate

    ratings = load_ratings(ensure_daily_ratings(demo=True))
    odds_events, _, _ = fetch_odds_snapshot(demo=True)
    demo_shift: timedelta | None = None
    if odds_events:
        first = min(e["commence_time"] for e in odds_events if isinstance(e.get("commence_time"), datetime))
        demo_shift = (now + timedelta(hours=3)) - first
        for e in odds_events:
            if isinstance(e.get("commence_time"), datetime):
                e["commence_time"] = e["commence_time"] + demo_shift

    et_days = et_dates_for_runner(now)
    all_slate: list[dict[str, Any]] = []
    for d in et_days:
        if DEMO_SLATE_FIXTURE.exists():
            slate = load_demo_slate(DEMO_SLATE_FIXTURE)
            if demo_shift is not None:
                for r in slate:
                    if isinstance(r.get("commence_time"), datetime):
                        r["commence_time"] = r["commence_time"] + demo_shift
        else:
            slate = build_slate(et_day=d, odds_events=odds_events, espn_rows=[])
        all_slate.extend(slate)

    return refresh_preview_from_snapshot(
        odds_events,
        all_slate,
        ratings=ratings,
        now=now,
        ledger_path=ledger_path,
        demo=True,
        build_site=build_site,
    )


def rebuild_ncaam_page_from_preview() -> None:
    from sharp_scout.site.ncaam_page import build_ncaam_page

    build_ncaam_page()