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
        "stage_cards": [],
        "disagreements": [],
    }


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    p = path or LEDGER_PATH
    if not p.exists():
        return empty_ledger()
    data = json.loads(p.read_text())
    data.setdefault("plays", [])
    data.setdefault("stage_cards", [])
    data.setdefault("disagreements", [])
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


def _logical_play_key(play: dict[str, Any]) -> str:
    """Same actionable bet regardless of book, window, or alternate line."""
    from sharp_scout.copy.explain import _signal_group_key

    return "|".join(str(p) for p in _signal_group_key(play))


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
    """Append new validated plays to the ledger (deduped).

    Replaces any pending play on the same game/market/side so only the
    latest best line/book survives across pipeline runs.
    """
    ledger = load_ledger(path)
    existing = {_play_key(p) for p in ledger["plays"]}
    added = 0
    replaced = 0
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
            "close_line": None,
            "close_price": None,
            "close_book": None,
            "clv_points": None,
            "clv_prob": None,
            "clv_at": None,
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
        logical = _logical_play_key(row)
        before_len = len(ledger["plays"])
        ledger["plays"] = [
            p
            for p in ledger["plays"]
            if (p.get("status") or "pending") != "pending" or _logical_play_key(p) != logical
        ]
        if len(ledger["plays"]) < before_len:
            replaced += 1
        existing = {_play_key(p) for p in ledger["plays"]}
        ledger["plays"].append(row)
        existing.add(key)
        added += 1
    save_ledger(ledger, path)
    logger.info(
        "Ledger: added %d plays, replaced %d pending (total %d)",
        added,
        replaced,
        len(ledger["plays"]),
    )
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


def append_stage_cards(
    cards: list[dict[str, Any]],
    *,
    season: int | None = None,
    week: int | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Upsert per-game stage pick cards (one row per event+market)."""
    ledger = load_ledger(path)
    existing = {
        f"{c.get('event_id')}|{c.get('market')}": i
        for i, c in enumerate(ledger.get("stage_cards") or [])
    }
    for card in cards:
        key = f"{card.get('event_id')}|{card.get('market')}"
        row = {
            **card,
            "season": season,
            "week": week,
            "created_at": _now(),
            "status": "pending",
            "results": {},  # stage -> win/loss/push
            "home_score": None,
            "away_score": None,
            "settled_at": None,
        }
        if key in existing:
            # Keep settlement if already graded
            old = ledger["stage_cards"][existing[key]]
            if old.get("status") not in (None, "pending"):
                continue
            row["created_at"] = old.get("created_at") or row["created_at"]
            ledger["stage_cards"][existing[key]] = row
        else:
            ledger.setdefault("stage_cards", []).append(row)
            existing[key] = len(ledger["stage_cards"]) - 1
    save_ledger(ledger, path)
    return ledger


def append_disagreements(
    records: list[dict[str, Any]],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Upsert model-vs-market disagreement records (deduped per event/market/side/week)."""
    ledger = load_ledger(path)
    existing = {
        _disagreement_key(d): i for i, d in enumerate(ledger.get("disagreements") or [])
    }
    added = updated = 0
    for rec in records:
        key = _disagreement_key(rec)
        if key in existing:
            old = ledger["disagreements"][existing[key]]
            # Preserve any manual category override and settled outcome
            rec["category_manual"] = old.get("category_manual") or rec.get("category_manual")
            rec["outcome"] = old.get("outcome") or rec.get("outcome")
            rec["created_at"] = old.get("created_at") or rec.get("created_at")
            ledger["disagreements"][existing[key]] = rec
            updated += 1
        else:
            ledger.setdefault("disagreements", []).append(rec)
            existing[key] = len(ledger["disagreements"]) - 1
            added += 1
    save_ledger(ledger, path)
    logger.info("Disagreements: added %d, updated %d (total %d)", added, updated, len(ledger["disagreements"]))
    return ledger


def _disagreement_key(rec: dict[str, Any]) -> str:
    return "|".join(
        str(rec.get(k) or "")
        for k in ("event_id", "market", "side", "season", "week")
    )


def settle_from_scores(
    scores: list[dict[str, Any]],
    path: Path | None = None,
) -> dict[str, Any]:
    """scores: [{home_team, away_team, home_score, away_score, event_id?}, ...]"""
    from sharp_scout.stage_picks import settle_stage_pick

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

    # Grade stage cards (ATS / ML by stage side)
    stage_settled = 0
    for card in ledger.get("stage_cards") or []:
        if card.get("status") not in (None, "pending"):
            continue
        g = None
        if card.get("event_id") and str(card["event_id"]) in index:
            g = index[str(card["event_id"])]
        else:
            g = index.get(f"{card.get('away_team')}@{card.get('home_team')}")
        if not g or g.get("home_score") is None or g.get("away_score") is None:
            continue
        hs, as_ = int(g["home_score"]), int(g["away_score"])
        results = {}
        for stage, pick in (card.get("picks") or {}).items():
            if not pick.get("available") or not pick.get("side"):
                continue
            # Prefer home current_line from money/public/rlm for ATS grading
            line = pick.get("line")
            if card.get("market") == "spread" and line is None:
                for alt in ("money", "public", "rlm", "sharp"):
                    alt_line = ((card.get("picks") or {}).get(alt) or {}).get("line")
                    if alt_line is not None:
                        line = alt_line
                        break
            results[stage] = settle_stage_pick(
                pick.get("side"),
                home_score=hs,
                away_score=as_,
                market=card.get("market") or "spread",
                line=line if card.get("market") == "spread" else None,
            )
        card["results"] = results
        card["home_score"] = hs
        card["away_score"] = as_
        card["status"] = "settled"
        card["settled_at"] = _now()
        stage_settled += 1

    # Fill Closing Line Value for plays whose closing line is now available.
    try:
        from sharp_scout.ledger.clv import finalize_closing_lines

        finalize_closing_lines(ledger)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CLV finalize skipped: %s", exc)

    # Learn which disagreement categories actually pay off: copy the settled play's
    # outcome onto the matching disagreement record.
    play_outcome: dict[str, str] = {}
    for play in ledger["plays"]:
        st = play.get("status")
        if st in ("win", "loss", "push"):
            play_outcome[_disagreement_key(play)] = st
    for rec in ledger.get("disagreements") or []:
        if rec.get("outcome"):
            continue
        outcome = play_outcome.get(_disagreement_key(rec))
        if outcome:
            rec["outcome"] = outcome

    save_ledger(ledger, path)
    logger.info("Settled %d plays, %d stage cards", settled, stage_settled)
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

    # Per-stage ATS/ML records from stage_cards
    stage_records: dict[str, dict[str, Any]] = {}
    for card in ledger.get("stage_cards") or []:
        for stage, result in (card.get("results") or {}).items():
            bucket = stage_records.setdefault(
                stage, {"wins": 0, "losses": 0, "pushes": 0, "pending": 0}
            )
            if result == "win":
                bucket["wins"] += 1
            elif result == "loss":
                bucket["losses"] += 1
            elif result == "push":
                bucket["pushes"] += 1
            else:
                bucket["pending"] += 1
        if card.get("status") in (None, "pending"):
            for stage, pick in (card.get("picks") or {}).items():
                if pick.get("available") and pick.get("side"):
                    bucket = stage_records.setdefault(
                        stage, {"wins": 0, "losses": 0, "pushes": 0, "pending": 0}
                    )
                    if stage not in (card.get("results") or {}):
                        bucket["pending"] += 1

    for stage, b in stage_records.items():
        d = b["wins"] + b["losses"]
        b["record"] = f"{b['wins']}-{b['losses']}" + (f"-{b['pushes']}" if b["pushes"] else "")
        b["win_pct"] = (b["wins"] / d) if d else None

    from sharp_scout.analysis.disagreement import summarize_disagreements
    from sharp_scout.ledger.clv import summarize_clv

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
        "stage_records": stage_records,
        "clv": summarize_clv(ledger),
        "disagreements": summarize_disagreements(ledger.get("disagreements") or []),
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