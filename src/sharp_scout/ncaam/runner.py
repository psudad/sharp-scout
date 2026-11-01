"""NCAAM looping runner — snapshots, locks, site build, heartbeat."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR, ROOT
from sharp_scout.data import line_store
from sharp_scout.data.action_network import ActionNetworkClient
from sharp_scout.data.odds_api import OddsClient, OddsAPIError
from sharp_scout.ncaam.candidates import NCAAM_BOOKS, evaluate_game, pick_best_per_game
from sharp_scout.ncaam.credits import (
    CREDITS_PER_ODDS_CALL,
    record_spend,
    should_skip_snapshot,
)
from sharp_scout.ncaam.espn import et_dates_for_runner, fetch_scoreboard_et_day
from sharp_scout.ledger.tracker import load_ledger
from sharp_scout.ncaam.lock import LEDGER_PATH, append_lock, find_play, lock_window, record_missed, LockWindow
from sharp_scout.ncaam.ratings import ensure_daily_ratings, load_ratings
from sharp_scout.ncaam.rules import apply_daily_cap
from sharp_scout.ncaam.settle import settle_ncaam_ledger
from sharp_scout.ncaam.slate import build_slate, load_demo_slate, save_slate
from sharp_scout.sports import NCAAM, get_sport
from sharp_scout.site.ncaam_page import build_ncaam_page, NCAAM_SIGNALS_PATH

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
HEARTBEAT_PATH = DATA_DIR / "ncaam" / "runner_heartbeat.json"
DEMO_ODDS_FIXTURE = ROOT / "tests" / "fixtures" / "ncaam" / "demo_odds.json"
DEMO_SLATE_FIXTURE = ROOT / "tests" / "fixtures" / "ncaam" / "demo_slate.json"


def write_heartbeat(*, runner_id: str, note: str = "") -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(
        json.dumps(
            {
                "runner_id": runner_id,
                "at": datetime.now(timezone.utc).isoformat(),
                "note": note,
            },
            indent=2,
        )
        + "\n"
    )


def another_runner_live(*, max_age_min: float = 10.0) -> bool:
    if not HEARTBEAT_PATH.exists():
        return False
    try:
        data = json.loads(HEARTBEAT_PATH.read_text())
        at = datetime.fromisoformat(str(data.get("at")).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - at).total_seconds() / 60.0
        return age < max_age_min
    except Exception:
        return False


def fetch_odds_snapshot(*, demo: bool) -> tuple[list[dict[str, Any]], int | None]:
    if demo:
        if DEMO_ODDS_FIXTURE.exists():
            raw = json.loads(DEMO_ODDS_FIXTURE.read_text())
            for ev in raw:
                ct = ev.get("commence_time")
                if isinstance(ct, str):
                    ev["commence_time"] = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            return raw, None
        return [], None
    client = OddsClient(sport=NCAAM)
    remaining_before = None
    try:
        events = client.fetch_odds(
            markets="spreads,h2h",
            bookmakers=",".join(NCAAM_BOOKS),
        )
        remaining_before = client.last_remaining
        return events, remaining_before
    except OddsAPIError as exc:
        logger.error("Odds snapshot failed: %s", exc)
        return [], remaining_before


def run_pass(
    *,
    demo: bool = False,
    now: datetime | None = None,
    ledger_path: Path | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    ledger_path = ledger_path or LEDGER_PATH
    ensure_daily_ratings(demo=demo)
    ratings = load_ratings()
    if not demo:
        settle_ncaam_ledger(path=ledger_path)

    skip, reason = should_skip_snapshot(remaining_header=None)
    odds_events: list[dict[str, Any]] = []
    if demo or not skip:
        odds_events, remaining = fetch_odds_snapshot(demo=demo)
        if not demo and odds_events:
            record_spend(CREDITS_PER_ODDS_CALL, remaining_header=remaining)
            line_store.record_snapshot(odds_events, sharp_only=False)
    elif skip:
        logger.info("Skipping odds snapshot: %s", reason)

    et_days = et_dates_for_runner(now)
    all_slate: list[dict[str, Any]] = []
    for d in et_days:
        if demo and DEMO_SLATE_FIXTURE.exists():
            slate = load_demo_slate(DEMO_SLATE_FIXTURE)
        else:
            espn = fetch_scoreboard_et_day(d)
            slate = build_slate(et_day=d, odds_events=odds_events, espn_rows=espn)
            if not demo:
                save_slate(slate, et_day=d)
        all_slate.extend(slate)

    odds_by_id = {str(e.get("event_id")): e for e in odds_events}
    tags: dict[str, Any] = {}
    if not demo:
        try:
            an = ActionNetworkClient(league="ncaam")
            for row in an.fetch_scoreboard():
                tags[str(row.get("event_id") or row.get("id") or "")] = row
        except Exception as exc:  # noqa: BLE001
            logger.warning("Action Network splits skipped: %s", exc)

    candidates: list[dict[str, Any]] = []
    locked: list[dict[str, Any]] = []
    for game in all_slate:
        tip = game.get("commence_time")
        if not isinstance(tip, datetime):
            continue
        window = lock_window(now, tip)
        eid = str(game.get("espn_id") or "")
        ledger = __import__("sharp_scout.ledger.tracker", fromlist=["load_ledger"]).load_ledger(ledger_path)
        if find_play(ledger, eid):
            continue
        if window == LockWindow.MISSED:
            record_missed(eid, tip=tip, path=ledger_path)
            continue
        if window not in (LockWindow.PRIMARY, LockWindow.LATE):
            continue
        oid = game.get("odds_event_id")
        ev = odds_by_id.get(str(oid)) if oid else None
        if not ev and demo:
            ev = odds_events[0] if odds_events else None
        if not ev:
            append_lock(
                {
                    "espn_id": eid,
                    "event_id": eid,
                    "status": "no_play",
                    "tip": tip.isoformat(),
                    "lead_min": (tip - now).total_seconds() / 60.0,
                    "market": "spreads",
                    "late_lock": window == LockWindow.LATE,
                    "inputs_sha256": "",
                },
                path=ledger_path,
                allow_no_play=True,
            )
            continue
        for c in evaluate_game(game, ev, ratings, now=now):
            c["et_day"] = tip.astimezone(ET).date().isoformat()
            candidates.append(c)

    best = pick_best_per_game(candidates)
    et_today = now.astimezone(ET).date().isoformat()
    day_picks = apply_daily_cap(list(best.values()), et_day=now.astimezone(ET).date())

    for play in day_picks:
        tip = play.get("tip")
        if isinstance(tip, datetime):
            play["tip"] = tip.isoformat()
            play["lead_min"] = round(
                (tip - now).total_seconds() / 60.0,
                1,
            )
        play["late_lock"] = lock_window(now, tip if isinstance(tip, datetime) else datetime.fromisoformat(str(play["tip"]).replace("Z", "+00:00"))) == LockWindow.LATE
        play["status"] = "pending"
        play["inputs_sha256"] = __import__("sharp_scout.ncaam.lock", fromlist=["inputs_sha256"]).inputs_sha256(
            {"game": play.get("espn_id"), "ev": play.get("ev")}
        )
        append_lock(play, path=ledger_path)
        saved = find_play(load_ledger(ledger_path), str(play.get("espn_id")))
        locked.append(saved or play)

    signals = {
        "generated_at": now.isoformat(),
        "model_version": get_sport("ncaam").key,
        "locks": locked,
        "candidates_n": len(candidates),
    }
    NCAAM_SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    NCAAM_SIGNALS_PATH.write_text(json.dumps(signals, indent=2, default=str) + "\n")
    build_ncaam_page()

    if commit and locked and not demo:
        _git_commit_push()

    return {"locked": len(locked), "candidates": len(candidates), "skip_reason": reason}


def _git_commit_push() -> None:
    script = ROOT / "scripts" / "ci_git_push_retry.sh"
    if not script.exists():
        return
    env = os.environ.copy()
    env["ADD_PATHS"] = "data/ncaam/ data/ncaam_ledger.json docs/ncaam.html docs/ncaam_ledger.json docs/ncaam_record.json"
    subprocess.run(["bash", str(script), "chore(ncaam): lock picks"], cwd=ROOT, env=env, check=False)


def run_loop(
    *,
    demo: bool = False,
    pass_every_min: int = 15,
    budget_min: int = 340,
    runner_id: str | None = None,
) -> int:
    runner_id = runner_id or f"ncaam-{os.getpid()}"
    if another_runner_live() and not demo:
        logger.info("Another NCAAM runner is live; exiting")
        return 0
    deadline = datetime.now(timezone.utc) + timedelta(minutes=budget_min)
    while datetime.now(timezone.utc) < deadline:
        write_heartbeat(runner_id=runner_id, note="pass")
        run_pass(demo=demo, commit=not demo)
        if demo:
            break
        time.sleep(max(60, pass_every_min * 60))
    return 0
