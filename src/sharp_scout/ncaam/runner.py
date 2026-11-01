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
from sharp_scout.data.odds_api import OddsClient, OddsAPIError
from sharp_scout.ncaam.candidates import NCAAM_BOOKS, evaluate_game, pick_best_per_game
from sharp_scout.ncaam.credits import (
    CREDITS_PER_ODDS_CALL,
    pass_interval_min,
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
NCAAM_LINE_HISTORY_PATH = DATA_DIR / "ncaam" / "line_history.json"
EXITED_NOTE = "exited"
# Paths the NCAAM runner owns (committed after locks and at end of run).
NCAAM_COMMIT_PATHS = [
    "data/ncaam/",
    "data/ncaam_ledger.json",
    "data/ncaam_latest_signals.json",
    "docs/ncaam.html",
    "docs/ncaam_ledger.json",
    "docs/ncaam_record.json",
]
# Only spend Odds API credits when a game is inside the lock window (T-90..T-5).
SNAPSHOT_LOOKAHEAD_MIN = 95
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
        if data.get("note") == EXITED_NOTE:
            return False
        at = datetime.fromisoformat(str(data.get("at")).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - at).total_seconds() / 60.0
        return age < max_age_min
    except Exception:
        return False


def fetch_odds_snapshot(*, demo: bool) -> tuple[list[dict[str, Any]], int | None, int | None]:
    if demo:
        if DEMO_ODDS_FIXTURE.exists():
            raw = json.loads(DEMO_ODDS_FIXTURE.read_text())
            for ev in raw:
                ct = ev.get("commence_time")
                if isinstance(ct, str):
                    ev["commence_time"] = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            return raw, None, None
        return [], None, None
    client = OddsClient(sport=NCAAM)
    try:
        events = client.fetch_odds(
            markets="spreads,h2h",
            bookmakers=",".join(NCAAM_BOOKS),
        )
        return events, client.last_remaining, client.last_cost
    except OddsAPIError as exc:
        logger.error("Odds snapshot failed: %s", exc)
        return [], client.last_remaining, client.last_cost


def _games_near_lock(rows: list[dict[str, Any]], now: datetime) -> int:
    n = 0
    for r in rows:
        tip = r.get("commence_time")
        if not isinstance(tip, datetime):
            continue
        lead = (tip - now).total_seconds() / 60.0
        if 5 < lead <= SNAPSHOT_LOOKAHEAD_MIN:
            n += 1
    return n


def _locked_today(ledger_path: Path, et_day: str) -> tuple[int, float]:
    plays = 0
    units = 0.0
    for p in load_ledger(ledger_path).get("plays") or []:
        if not p.get("side") or p.get("status") in ("no_play", "missed"):
            continue
        tip = p.get("tip")
        try:
            tip_dt = datetime.fromisoformat(str(tip).replace("Z", "+00:00"))
        except ValueError:
            continue
        if tip_dt.astimezone(ET).date().isoformat() != et_day:
            continue
        plays += 1
        units += float(p.get("units") or 0)
    return plays, units


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

    et_days = et_dates_for_runner(now)
    espn_by_day: dict[Any, list[dict[str, Any]]] = {}
    if not demo:
        for d in et_days:
            espn_by_day[d] = fetch_scoreboard_et_day(d)

    skip, reason = should_skip_snapshot(remaining_header=None)
    if not demo and not skip:
        near = _games_near_lock([r for rows in espn_by_day.values() for r in rows], now)
        if near == 0:
            skip, reason = True, "no_games_near_lock_window"
    odds_events: list[dict[str, Any]] = []
    if demo or not skip:
        odds_events, remaining, cost = fetch_odds_snapshot(demo=demo)
        if not demo and (odds_events or (cost or 0) > 0):
            spent = cost if cost is not None else CREDITS_PER_ODDS_CALL
            record_spend(spent, remaining_header=remaining)
            logger.info("NCAAM odds snapshot cost=%s remaining=%s", spent, remaining)
        if not demo and odds_events:
            line_store.record_snapshot(odds_events, sharp_only=False, path=NCAAM_LINE_HISTORY_PATH)
    elif skip:
        logger.info("Skipping odds snapshot: %s", reason)

    demo_shift: timedelta | None = None
    if demo and odds_events:
        # Fixtures carry fixed tip times; move them so the first game tips 60 min from now.
        first = min(e["commence_time"] for e in odds_events if isinstance(e.get("commence_time"), datetime))
        demo_shift = (now + timedelta(minutes=60)) - first
        for e in odds_events:
            if isinstance(e.get("commence_time"), datetime):
                e["commence_time"] = e["commence_time"] + demo_shift
            for bm in (e.get("bookmakers") or {}).values():
                lu = bm.get("last_update") if isinstance(bm, dict) else None
                if isinstance(lu, str):
                    try:
                        bm["last_update"] = (datetime.fromisoformat(lu.replace("Z", "+00:00")) + demo_shift).isoformat()
                    except ValueError:
                        pass

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
    done_n, done_u = _locked_today(ledger_path, et_today)
    day_picks = apply_daily_cap(
        list(best.values()),
        et_day=now.astimezone(ET).date(),
        already_plays=done_n,
        already_units=done_u,
    )

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

    sharp_locked = 0
    if not demo:
        sharp_locked = run_sharp_systems(now=now, et_days=et_days, slate=all_slate, odds_by_id=odds_by_id, ratings=ratings)

    signals = {
        "generated_at": now.isoformat(),
        "model_version": get_sport("ncaam").key,
        "locks": locked,
        "candidates_n": len(candidates),
    }
    if demo:
        # Demo fixtures never touch the live board: write next to the temp ledger.
        signals_path = ledger_path.parent / "ncaam_latest_signals.json"
        docs_dir = ledger_path.parent / "docs"
    else:
        signals_path = NCAAM_SIGNALS_PATH
        docs_dir = None
    signals_path.parent.mkdir(parents=True, exist_ok=True)
    signals_path.write_text(json.dumps(signals, indent=2, default=str) + "\n")
    build_ncaam_page(docs_dir=docs_dir, signals_path=signals_path, ledger_path=ledger_path)

    if commit and (locked or sharp_locked) and not demo:
        _git_commit_push()

    return {
        "locked": len(locked),
        "sharp_locked": sharp_locked,
        "candidates": len(candidates),
        "skip_reason": reason,
    }


def run_sharp_systems(
    *,
    now: datetime,
    et_days: list[Any],
    slate: list[dict[str, Any]],
    odds_by_id: dict[str, dict[str, Any]],
    ratings: dict[str, dict[str, float]],
) -> int:
    """Sharp 3 and Sharp 3.5 (unlisted page only). Never raises; never spends Odds API credits."""
    try:
        from sharp_scout.ncaam.espn import fetch_final_scores
        from sharp_scout.ncaam.situational import Situational
        from sharp_scout.ncaam.splits import fetch_splits
        from sharp_scout.ncaam.systems import ENGINES, ledger_path, run_systems

        try:
            today = now.astimezone(ET).date()
            scores = fetch_final_scores(start=today - timedelta(days=2), end=today)
            for eng in ENGINES:
                if ledger_path(eng).exists():
                    settle_ncaam_ledger(path=ledger_path(eng), scores=scores)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sharp ledgers settle skipped: %s", type(exc).__name__)
        splits = fetch_splits(list(et_days))
        logger.info(
            "Action Network NCAAB splits: games=%s with_money=%s auth=%s http=%s",
            len(splits.get("games") or []),
            splits.get("n_with_money"),
            splits.get("auth_mode"),
            splits.get("status"),
        )
        res = run_systems(
            now=now,
            slate=slate,
            odds_by_id=odds_by_id,
            ratings=ratings,
            splits_result=splits,
            situational_factory=lambda d: Situational(d),
        )
        return len(res.get("locked") or [])
    except Exception:  # noqa: BLE001 - must never break the New System pass
        logger.exception("Sharp systems pass failed")
        return 0


def _git_commit_push(message: str = "chore(ncaam): lock picks", *, trigger_pages: bool = True) -> bool:
    """Commit NCAAM-owned files and push with rebase/retry.

    Backs up the NCAAM files first. If the retry script hits a rebase conflict and resets to
    origin/main, its RERUN hook restores the backup (locks + credit budget are never lost) and
    rebuilds the page before restaging. Unrelated dirty files are autostashed for the rebase.
    """
    import shutil
    import sys
    import tempfile

    script = ROOT / "scripts" / "ci_git_push_retry.sh"
    if not script.exists():
        return False
    backup = Path(tempfile.mkdtemp(prefix="ncaam_backup_"))
    for rel in ("data/ncaam", "data/ncaam_ledger.json", "data/ncaam_latest_signals.json"):
        src = ROOT / rel
        if src.is_dir():
            shutil.copytree(src, backup / rel, dirs_exist_ok=True)
        elif src.exists():
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, backup / rel)
    env = os.environ.copy()
    env["ADD_PATHS"] = " ".join(NCAAM_COMMIT_PATHS)
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "rebase.autoStash"
    env["GIT_CONFIG_VALUE_0"] = "true"
    rerun = [sys.executable, str(ROOT / "scripts" / "run_ncaam.py"), "--restore-from", str(backup)]
    res = subprocess.run(["bash", str(script), message, *rerun], cwd=ROOT, env=env, check=False)
    ok = res.returncode == 0
    if ok and trigger_pages and os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GH_TOKEN"):
        # Pushes made with GITHUB_TOKEN do not trigger pages.yml; dispatch it so locks show before tip.
        subprocess.run(["gh", "workflow", "run", "pages.yml", "--ref", "main"], cwd=ROOT, check=False)
    return ok


def restore_from_backup(backup: Path) -> None:
    """Copy backed-up NCAAM files over the working tree and rebuild the page (conflict recovery)."""
    import shutil

    for rel in ("data/ncaam", "data/ncaam_ledger.json", "data/ncaam_latest_signals.json"):
        src = backup / rel
        dst = ROOT / rel
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    build_ncaam_page()


def run_loop(
    *,
    demo: bool = False,
    pass_every_min: int = 15,
    budget_min: int = 340,
    runner_id: str | None = None,
    ledger_path: Path | None = None,
) -> int:
    runner_id = runner_id or f"ncaam-{os.getpid()}"
    if another_runner_live() and not demo:
        logger.info("Another NCAAM runner is live; exiting")
        return 0
    deadline = datetime.now(timezone.utc) + timedelta(minutes=budget_min)
    try:
        while datetime.now(timezone.utc) < deadline:
            write_heartbeat(runner_id=runner_id, note="pass")
            try:
                run_pass(demo=demo, commit=not demo, ledger_path=ledger_path)
            except Exception:  # noqa: BLE001 - one bad pass must not kill the loop
                logger.exception("NCAAM pass failed; will retry next pass")
            if demo:
                break
            left = (deadline - datetime.now(timezone.utc)).total_seconds()
            if left <= 60:
                break
            # Never sleep past the budget, so the job ends well inside timeout-minutes.
            # Credit guard: 30-minute cadence once 100 credits are used today.
            time.sleep(min(max(60, pass_interval_min(pass_every_min) * 60), left))
    finally:
        if not demo:
            write_heartbeat(runner_id=runner_id, note=EXITED_NOTE)
    return 0
