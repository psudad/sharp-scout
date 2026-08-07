"""Persistent play ledger — tracks plays, settles results, computes record."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR, ROOT

logger = logging.getLogger(__name__)

LEDGER_PATH = DATA_DIR / "ledger.json"
DEFAULT_UNITS = {"play": 1.5, "lean": 1.0, "candidate": 0.5}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_ledger() -> dict[str, Any]:
    return {
        "updated_at": _now(),
        "starting_units": 100.0,
        "plays": [],
    }


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    p = path or LEDGER_PATH
    if not p.exists():
        return empty_ledger()
    data = json.loads(p.read_text())
    data.setdefault("plays", [])
    data.setdefault("starting_units", 100.0)
    return data


def save_ledger(ledger: dict[str, Any], path: Path | None = None) -> Path:
    p = path or LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = _now()
    p.write_text(json.dumps(ledger, indent=2, default=str) + "\n")
    return p


def _play_key(play: dict[str, Any]) -> str:
    return "|".join(
        [
            str(play.get("event_id") or ""),
            str(play.get("player_name") or ""),
            str(play.get("market") or ""),
            str(play.get("side") or ""),
            str(play.get("line") if play.get("line") is not None else ""),
            str(play.get("book") or ""),
            str(play.get("window") or play.get("pregame_window") or ""),
        ]
    )


def units_for_tier(tier: str) -> float:
    return float(DEFAULT_UNITS.get(tier, 1.0))


def american_profit(units: float, price: float) -> float:
    """Profit (not including stake) on a win at American odds."""
    if price > 0:
        return units * (price / 100.0)
    return units * (100.0 / abs(price))


def append_signals(
    signals: list[dict[str, Any]],
    *,
    only_validated: bool = True,
    season: int | None = None,
    week: int | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Append new validated plays to the ledger (deduped)."""
    ledger = load_ledger(path)
    existing = {_play_key(p) for p in ledger["plays"]}
    added = 0
    for s in signals:
        if only_validated and not s.get("filter_passed"):
            continue
        if s.get("tier") == "rejected":
            continue
        row = {
            "id": str(uuid.uuid4())[:8],
            "created_at": _now(),
            "event_id": s.get("event_id"),
            "season": season,
            "week": week,
            "kickoff": s.get("kickoff") or s.get("commence_time"),
            "away_team": s.get("away_team"),
            "home_team": s.get("home_team"),
            "play_type": s.get("play_type") or ("prop" if s.get("player_name") else "side"),
            "player_name": s.get("player_name"),
            "market": s.get("market"),
            "side": s.get("side"),
            "line": s.get("line"),
            "book": s.get("book"),
            "price": s.get("price"),
            "units": units_for_tier(s.get("tier") or "lean"),
            "tier": s.get("tier") or "lean",
            "edge": s.get("edge"),
            "p_true": s.get("p_true"),
            "p_mkt": s.get("p_mkt"),
            "model_spread": s.get("model_spread"),
            "model_total": s.get("model_total"),
            "model_mean": s.get("model_mean"),
            "is_alternate": s.get("is_alternate", False),
            "window": s.get("window") or s.get("pregame_window"),
            "rationale": s.get("rationale") or "",
            "status": "pending",
            "home_score": None,
            "away_score": None,
            "prop_result": None,
            "pnl_units": None,
            "settled_at": None,
        }
        key = _play_key(row)
        if key in existing:
            continue
        # Also skip if same matchup/market/side already pending
        ledger["plays"].append(row)
        existing.add(key)
        added += 1
    save_ledger(ledger, path)
    logger.info("Ledger: added %d plays (total %d)", added, len(ledger["plays"]))
    return ledger


def settle_play(
    play: dict[str, Any],
    home_score: int,
    away_score: int,
    *,
    prop_value: float | None = None,
) -> dict[str, Any]:
    """Grade a single play from final scores (sides) or prop_value (player props)."""
    market = play.get("market")
    side = play.get("side")
    line = play.get("line")
    price = float(play.get("price") or -110)
    units = float(play.get("units") or 1.0)

    # Player props: require observed prop_value
    if str(market or "").startswith("player_") or play.get("play_type") == "prop":
        if prop_value is None:
            return play  # leave pending
        play["prop_result"] = prop_value
        if line is None:
            # anytime TD style
            status = "win" if prop_value >= 1 else "loss"
        else:
            diff = float(prop_value) - float(line)
            if abs(diff) < 1e-9:
                status = "push"
            elif side == "over":
                status = "win" if diff > 0 else "loss"
            else:
                status = "win" if diff < 0 else "loss"
        if status == "win":
            pnl = american_profit(units, price)
        elif status == "loss":
            pnl = -units
        else:
            pnl = 0.0
        play["status"] = status
        play["pnl_units"] = round(pnl, 4)
        play["settled_at"] = _now()
        play["home_score"] = home_score
        play["away_score"] = away_score
        return play

    status = "void"
    if market == "h2h":
        if home_score == away_score:
            status = "push"
        elif side == "home":
            status = "win" if home_score > away_score else "loss"
        else:
            status = "win" if away_score > home_score else "loss"

    elif market == "spreads":
        if line is None:
            status = "void"
        else:
            if side == "home":
                margin = home_score + float(line) - away_score
            else:
                margin = away_score + float(line) - home_score
            if abs(margin) < 1e-9:
                status = "push"
            else:
                status = "win" if margin > 0 else "loss"

    elif market == "totals":
        if line is None:
            status = "void"
        else:
            total = home_score + away_score
            diff = total - float(line)
            if abs(diff) < 1e-9:
                status = "push"
            elif side == "over":
                status = "win" if diff > 0 else "loss"
            else:
                status = "win" if diff < 0 else "loss"

    if status == "win":
        pnl = american_profit(units, price)
    elif status == "loss":
        pnl = -units
    else:
        pnl = 0.0

    play["home_score"] = home_score
    play["away_score"] = away_score
    play["status"] = status
    play["pnl_units"] = round(pnl, 4)
    play["settled_at"] = _now()
    return play


def settle_from_scores(
    scores: list[dict[str, Any]],
    path: Path | None = None,
) -> dict[str, Any]:
    """scores: [{home_team, away_team, home_score, away_score, event_id?}, ...]"""
    ledger = load_ledger(path)
    index: dict[str, dict[str, Any]] = {}
    for g in scores:
        key = f"{g.get('away_team')}@{g.get('home_team')}"
        index[key] = g
        if g.get("event_id"):
            index[str(g["event_id"])] = g

    settled = 0
    for play in ledger["plays"]:
        if play.get("status") not in (None, "pending"):
            continue
        g = None
        if play.get("event_id") and str(play["event_id"]) in index:
            g = index[str(play["event_id"])]
        else:
            g = index.get(f"{play.get('away_team')}@{play.get('home_team')}")
        if not g:
            continue
        if g.get("home_score") is None or g.get("away_score") is None:
            continue
        settle_play(play, int(g["home_score"]), int(g["away_score"]))
        settled += 1

    save_ledger(ledger, path)
    logger.info("Settled %d plays", settled)
    return ledger


def compute_record(ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger = ledger or load_ledger()
    plays = ledger.get("plays") or []
    wins = losses = pushes = pending = void = 0
    pnl = 0.0
    by_week: dict[str, dict[str, Any]] = {}

    for p in plays:
        st = p.get("status") or "pending"
        if st == "win":
            wins += 1
        elif st == "loss":
            losses += 1
        elif st == "push":
            pushes += 1
        elif st == "void":
            void += 1
        else:
            pending += 1
        if p.get("pnl_units") is not None:
            pnl += float(p["pnl_units"])

        week_key = f"{p.get('season') or '?'} W{p.get('week') or '?'}"
        bucket = by_week.setdefault(
            week_key, {"wins": 0, "losses": 0, "pushes": 0, "pending": 0, "pnl": 0.0}
        )
        if st == "win":
            bucket["wins"] += 1
        elif st == "loss":
            bucket["losses"] += 1
        elif st == "push":
            bucket["pushes"] += 1
        elif st == "pending":
            bucket["pending"] += 1
        if p.get("pnl_units") is not None:
            bucket["pnl"] += float(p["pnl_units"])

    decided = wins + losses
    win_pct = (wins / decided) if decided else None
    starting = float(ledger.get("starting_units") or 100)
    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": pending,
        "void": void,
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "win_pct": win_pct,
        "pnl_units": round(pnl, 2),
        "bankroll_units": round(starting + pnl, 2),
        "starting_units": starting,
        "n_plays": len(plays),
        "by_week": by_week,
    }


def load_scores_from_schedules(seasons: list[int] | None = None) -> list[dict[str, Any]]:
    """Pull final scores from nflverse schedules for settlement."""
    from sharp_scout.data.nflfastr import load_schedules

    sched = load_schedules(seasons)
    if sched.empty:
        return []
    rows = []
    for _, r in sched.iterrows():
        hs, as_ = r.get("home_score"), r.get("away_score")
        if hs is None or as_ is None or (isinstance(hs, float) and hs != hs):
            continue
        try:
            rows.append(
                {
                    "home_team": r.get("home_team"),
                    "away_team": r.get("away_team"),
                    "home_score": int(hs),
                    "away_score": int(as_),
                    "season": int(r["season"]) if r.get("season") == r.get("season") else None,
                    "week": int(r["week"]) if r.get("week") == r.get("week") else None,
                    "game_id": r.get("game_id"),
                }
            )
        except (TypeError, ValueError):
            continue
    return rows