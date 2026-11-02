"""Run Sharp 3 and Sharp 3.5 next to the New System, each with its own ledger.

The two Sharp systems never touch the New System ledger and are never merged with it or
with each other. They reuse the runner's Odds API snapshot (no extra credits). Their
picks, records and per-game table are written only to data files read by the unlisted
page builder (scripts/build_ncaam_lab.py); nothing here writes into docs/.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR
from sharp_scout.ledger.tracker import load_ledger
from sharp_scout.ncaam import sharp3, sharp35
from sharp_scout.ncaam.conferences import is_mid_major
from sharp_scout.ncaam.lock import LockWindow, append_lock, find_play, inputs_sha256, lock_window
from sharp_scout.ncaam.splits import has_splits, match_to_slate

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
NCAAM_DATA = DATA_DIR / "ncaam"
MAX_GAMES_PER_DAY = 10
ENGINES = {
    sharp3.ENGINE: {"module": sharp3, "ledger": "sharp3_ledger.json", "tiers": sharp3.TIER_RANK},
    sharp35.ENGINE: {"module": sharp35, "ledger": "sharp35_ledger.json", "tiers": sharp35.TIER_RANK},
}
_STATE_FIELDS = (
    "result", "reason", "side", "market", "line", "price", "book", "line_source", "tier", "units",
    "conf", "edge", "gap", "money_pct", "ticket_pct", "flags", "price_estimated", "sim_rec",
    "novig", "margin_model", "signals", "orig_line", "orig_price", "splits_source",
)


def ledger_path(engine: str, data_dir: Path | None = None) -> Path:
    return (data_dir or NCAAM_DATA) / ENGINES[engine]["ledger"]


def state_path(day: date, data_dir: Path | None = None) -> Path:
    return (data_dir or NCAAM_DATA) / f"systems_{day.strftime('%Y%m%d')}.json"


def _load_json(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default


def _tip(game: dict[str, Any]) -> datetime | None:
    t = game.get("commence_time")
    if isinstance(t, datetime):
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def mid_major_by_side(game: dict[str, Any], splits: dict[str, Any] | None) -> dict[str, bool]:
    sp = splits or {}
    return {
        s: is_mid_major(
            an_conference=sp.get(f"{s}_conf") or None,
            espn_conference_id=str(game.get(f"{s}_conference_id") or "") or None,
        )
        for s in ("home", "away")
    }


def top_slots(entries: list[tuple[str, float]], limit: int = MAX_GAMES_PER_DAY) -> set[str]:
    """The 10-game throttle: ids of the top ``limit`` entries by money-minus-ticket gap."""
    ranked = sorted(entries, key=lambda e: (-float(e[1]), str(e[0])))
    return {eid for eid, _ in ranked[:limit]}


def pick_status(first_tier: str | None, tier: str, ranks: dict[str, int]) -> str:
    if first_tier is None:
        return "NEW"
    return "UPGRD" if ranks.get(tier, 0) > ranks.get(first_tier, 0) else "HOLD"


def _eligible(engine: str, ev: dict[str, Any]) -> bool:
    if engine == sharp3.ENGINE:
        return ev.get("result") == "play"
    return bool(ev.get("shortlisted"))


def _row(engine: str, game: dict[str, Any], ev: dict[str, Any], *, now: datetime, tip: datetime, status: str) -> dict[str, Any]:
    mod = ENGINES[engine]["module"]
    side = ev["side"]
    return {
        "espn_id": str(game.get("espn_id")),
        "event_id": str(game.get("odds_event_id") or game.get("espn_id")),
        "engine": engine,
        "model_version": mod.MODEL_VERSION,
        "market": ev.get("market") or "spreads",
        "side": side,
        "selection": game.get(f"{side}_team"),
        "line": ev.get("line"),
        "price": ev.get("price"),
        "book": ev.get("book"),
        "units": ev.get("units"),
        "tier": ev.get("tier"),
        "conf": ev.get("conf"),
        "edge": ev.get("edge"),
        "gap": ev.get("gap"),
        "money_pct": ev.get("money_pct"),
        "ticket_pct": ev.get("ticket_pct"),
        "flags": ev.get("flags") or [],
        "price_estimated": bool(ev.get("price_estimated")),
        "sim_rec": ev.get("sim_rec"),
        "pick_status": status,
        "home_team": game.get("home_team"),
        "away_team": game.get("away_team"),
        "tip": tip.isoformat(),
        "lead_min": round((tip - now).total_seconds() / 60.0, 1),
        "late_lock": lock_window(now, tip) == LockWindow.LATE,
        "status": "pending",
        "inputs_sha256": inputs_sha256({k: ev.get(k) for k in _STATE_FIELDS}),
    }


def run_systems(
    *,
    now: datetime,
    slate: list[dict[str, Any]],
    odds_by_id: dict[str, dict[str, Any]],
    ratings: dict[str, dict[str, float]],
    splits_result: dict[str, Any] | None,
    data_dir: Path | None = None,
    situational_factory: Callable[[date], Any] | None = None,
    allow_lock: bool = True,
) -> dict[str, Any]:
    """One pass for both Sharp systems. Returns {locked: [...], days: {...}}."""
    splits_result = splits_result or {}
    by_espn = match_to_slate(slate, splits_result.get("games") or [])
    by_day: dict[date, list[dict[str, Any]]] = {}
    for g in slate:
        tip = _tip(g)
        if tip:
            by_day.setdefault(tip.astimezone(ET).date(), []).append(g)
    locked: list[dict[str, Any]] = []
    for day, games in sorted(by_day.items()):
        sp_path = state_path(day, data_dir)
        state = _load_json(sp_path, {})
        state.setdefault("games", {})
        state["updated_at"] = now.isoformat()
        n_with = sum(1 for g in games if has_splits(by_espn.get(str(g.get("espn_id")))))
        n_games = len(games)
        state["splits"] = {
            "auth_mode": splits_result.get("auth_mode"),
            "status": splits_result.get("status"),
            "n_with_money": n_with,
            "n_games": n_games,
            "coverage": f"{n_with}/{n_games}",
        }
        logger.info(
            "Sharp 3 / Sharp 3.5 splits coverage for %s: %s/%s games",
            day.isoformat(),
            n_with,
            n_games,
        )
        sit = None
        if situational_factory is not None:
            try:
                sit = situational_factory(day)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Situational data unavailable: %s", type(exc).__name__)
        ledgers = {e: load_ledger(ledger_path(e, data_dir)) for e in ENGINES}
        evals: dict[str, dict[str, dict[str, Any]]] = {e: {} for e in ENGINES}
        prior_first: dict[str, dict[str, str | None]] = {e: {} for e in ENGINES}
        windows: dict[str, LockWindow] = {}
        for g in games:
            eid = str(g.get("espn_id") or "")
            tip = _tip(g)
            windows[eid] = lock_window(now, tip)
            sp = by_espn.get(eid)
            oid = g.get("odds_event_id")
            event = odds_by_id.get(str(oid)) if oid else None
            mm = mid_major_by_side(g, sp)
            entry = state["games"].setdefault(eid, {})
            entry.update(
                {
                    "tip": tip.isoformat(),
                    "home_team": g.get("home_team"),
                    "away_team": g.get("away_team"),
                    "has_splits": has_splits(sp),
                }
            )
            for e in ENGINES:
                prior = entry.get(e) or {}
                if prior.get("locked") or prior.get("final"):
                    continue
                prior_first[e][eid] = prior.get("first_tier")
                try:
                    if e == sharp3.ENGINE:
                        ev = sharp3.evaluate(g, sp, event, is_mid_major_by_side=mm)
                    else:
                        in_win = windows[eid] in (LockWindow.PRIMARY, LockWindow.LATE)
                        ev = sharp35.evaluate(
                            g, sp, event, ratings, is_mid_major_by_side=mm, situational=sit, with_star=in_win
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s evaluation failed for %s: %s", e, eid, type(exc).__name__)
                    ev = {"result": "warning", "reason": "Evaluation error"}
                evals[e][eid] = ev
                rec = {k: ev.get(k) for k in _STATE_FIELDS if ev.get(k) is not None}
                if ev.get("result") == "play" and not prior.get("first_tier"):
                    rec["first_tier"] = ev.get("tier")
                elif prior.get("first_tier"):
                    rec["first_tier"] = prior["first_tier"]
                entry[e] = rec
        for e, cfg in ENGINES.items():
            led = ledgers[e]
            locked_ids = {
                str(p.get("espn_id")): float(p.get("gap") or 0)
                for p in led.get("plays") or []
                if p.get("side") and str(p.get("espn_id")) in state["games"]
            }
            pool = list(locked_ids.items())
            for g in games:
                eid = str(g.get("espn_id"))
                ev = evals[e].get(eid)
                if eid in locked_ids or not ev:
                    continue
                if windows[eid] in (LockWindow.POST_TIP, LockWindow.MISSED):
                    continue
                if _eligible(e, ev):
                    pool.append((eid, float(ev.get("gap") or 0)))
            top = top_slots(pool)
            for g in games:
                eid = str(g.get("espn_id"))
                entry = state["games"][eid]
                rec = entry.get(e) or {}
                if eid in locked_ids:
                    play = find_play(led, eid)
                    if play:
                        rec.update({k: play.get(k) for k in ("side", "market", "line", "price", "book", "tier", "units", "edge", "conf", "gap", "pick_status", "locked_at")})
                        rec.update(result="play", locked=True)
                        entry[e] = rec
                    continue
                if rec.get("final"):
                    continue
                ev = evals[e].get(eid) or {}
                w = windows[eid]
                if _eligible(e, ev) and eid not in top:
                    rec["volume"] = True
                    rec["reason"] = "Volume (not played)"
                else:
                    rec.pop("volume", None)
                if w in (LockWindow.MISSED, LockWindow.POST_TIP):
                    rec["final"] = True
                    entry[e] = rec
                    continue
                if w not in (LockWindow.PRIMARY, LockWindow.LATE) or not allow_lock:
                    entry[e] = rec
                    continue
                if ev.get("result") != "play" or eid not in top:
                    entry[e] = rec
                    continue
                if ev.get("line_source") != "odds_api":
                    rec["reason"] = "Waiting for a live sportsbook line"
                    entry[e] = rec
                    continue
                if len(locked_ids) >= MAX_GAMES_PER_DAY:
                    rec["volume"] = True
                    rec["reason"] = "Volume (not played)"
                    entry[e] = rec
                    continue
                tip = _tip(g)
                status = pick_status(prior_first[e].get(eid), ev["tier"], cfg["tiers"])
                row = _row(e, g, ev, now=now, tip=tip, status=status)
                try:
                    append_lock(row, path=ledger_path(e, data_dir))
                except ValueError:
                    continue
                led = load_ledger(ledger_path(e, data_dir))
                ledgers[e] = led
                saved = find_play(led, eid) or row
                locked_ids[eid] = float(row.get("gap") or 0)
                rec.update(result="play", locked=True, pick_status=status, locked_at=saved.get("locked_at"))
                entry[e] = rec
                locked.append(saved)
        sp_path.parent.mkdir(parents=True, exist_ok=True)
        sp_path.write_text(json.dumps(state, indent=1, sort_keys=True, default=str) + "\n")
        if sit is not None:
            try:
                sit.save()
            except Exception:  # noqa: BLE001
                pass
    return {"locked": locked}


def record(ledger: dict[str, Any]) -> dict[str, Any]:
    w = l = p = 0
    pnl = risked = 0.0
    pending = 0
    for row in ledger.get("plays") or []:
        if not row.get("side"):
            continue
        st = row.get("status")
        u = float(row.get("units") or 0)
        if st == "win":
            w += 1
        elif st == "loss":
            l += 1
        elif st == "push":
            p += 1
        else:
            if st == "pending":
                pending += 1
            continue
        pnl += float(row.get("pnl_units") or 0)
        if st != "push":
            risked += u
    return {
        "wins": w,
        "losses": l,
        "pushes": p,
        "pending": pending,
        "units": round(pnl, 2),
        "roi": round(pnl / risked * 100.0, 1) if risked else None,
    }
