"""Display-only sharp-money comparator tags from committed split snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sharp_scout.nba.sharp_splits.store import find_game_splits, list_snapshots
from sharp_scout.utils.kickoff import parse_kickoff_utc

SHARP_MONEY_GAP_PT = 10

_SIDE_INDEX = {
    "spreads": {"away": 0, "home": 1},
    "totals": {"over": 0, "under": 1},
    "h2h": {"away": 0, "home": 1},
}


def _splits_block_key(market: str) -> str | None:
    """Key inside a snapshot game object (spread/total/ml, not Odds API market names)."""
    m = str(market or "").lower()
    if m == "h2h":
        return "ml"
    if m == "spreads":
        return "spread"
    if m == "totals":
        return "total"
    return None


def _side_index(market: str, side: str) -> int | None:
    m = str(market or "").lower()
    s = str(side or "").lower()
    return _SIDE_INDEX.get(m, {}).get(s)


def sharp_gap(bets: list[Any], money: list[Any], idx: int) -> float | None:
    try:
        b = float(bets[idx])
        m = float(money[idx])
    except (IndexError, TypeError, ValueError):
        return None
    return m - b


def alignment_for_play(
    play: dict[str, Any],
    game_splits: dict[str, Any] | None,
) -> dict[str, Any]:
    if (play.get("play_type") or "side") == "prop":
        return {"sharp_money_tag": "no_data", "sharp_money_gap_pt": None}

    market = str(play.get("market") or "")
    side = str(play.get("side") or "").lower()
    block_key = _splits_block_key(market)
    idx = _side_index(market, side)

    if game_splits is None or block_key is None or idx is None:
        return {"sharp_money_tag": "no_data", "sharp_money_gap_pt": None}

    block = game_splits.get(block_key) or {}
    bets = block.get("bets") or []
    money = block.get("money") or []
    if len(bets) < 2 or len(money) < 2:
        return {"sharp_money_tag": "no_data", "sharp_money_gap_pt": None}

    play_gap = sharp_gap(bets, money, idx)
    opp_gap = sharp_gap(bets, money, 1 - idx)
    if play_gap is None or opp_gap is None:
        return {"sharp_money_tag": "no_data", "sharp_money_gap_pt": None}

    tag = "no_signal"
    if play_gap >= SHARP_MONEY_GAP_PT:
        tag = "with_sharps"
    elif opp_gap >= SHARP_MONEY_GAP_PT:
        tag = "against_sharps"

    return {
        "sharp_money_tag": tag,
        "sharp_money_gap_pt": round(play_gap, 1),
    }


def _annotate_row(
    row: dict[str, Any],
    *,
    snapshots: list[dict[str, Any]],
    cache: dict[tuple[str, str, str], tuple[dict[str, Any] | None, Any]],
) -> None:
    away = str(row.get("away_team") or "")
    home = str(row.get("home_team") or "")
    kick = row.get("kickoff") or row.get("commence_time")
    cache_key = (away, home, str(kick))
    if cache_key not in cache:
        game, pulled = find_game_splits(
            away_team=away, home_team=home, kickoff=kick, snapshots=snapshots
        )
        cache[cache_key] = (game, pulled)
    game, pulled = cache[cache_key]
    row.update(alignment_for_play(row, game))
    if pulled is not None:
        row["sharp_money_snapshot_at"] = pulled.isoformat()


def annotate_signals_with_sharp_money(
    events: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> None:
    """Tag signals in-place. Does not filter or resize picks."""
    snapshots = list_snapshots()
    if not snapshots:
        for sig in signals:
            sig.update(alignment_for_play(sig, None))
        return

    by_eid = {str(ev.get("event_id")): ev for ev in events if ev.get("event_id")}
    cache: dict[tuple[str, str, str], tuple[dict[str, Any] | None, Any]] = {}
    for sig in signals:
        eid = str(sig.get("event_id") or "")
        ev = by_eid.get(eid)
        if ev:
            sig.setdefault("away_team", ev.get("away_team"))
            sig.setdefault("home_team", ev.get("home_team"))
            sig.setdefault("kickoff", ev.get("commence_time"))
        _annotate_row(sig, snapshots=snapshots, cache=cache)


def refresh_open_ledger_sharp_tags(ledger: dict[str, Any]) -> int:
    """Re-evaluate open plays before tip using the latest eligible snapshot."""
    snapshots = list_snapshots()
    if not snapshots:
        return 0
    cache: dict[tuple[str, str, str], tuple[dict[str, Any] | None, Any]] = {}
    updated = 0
    open_status = {"paper", "pending"}
    now = datetime.now(timezone.utc)
    for play in ledger.get("plays") or []:
        if str(play.get("status") or "").lower() not in open_status:
            continue
        kick = parse_kickoff_utc(play.get("kickoff"))
        if kick is not None and kick <= now:
            continue
        before = play.get("sharp_money_tag")
        _annotate_row(play, snapshots=snapshots, cache=cache)
        if play.get("sharp_money_tag") != before:
            play["sharp_money_evaluated_at"] = now.isoformat()
            updated += 1
        elif play.get("sharp_money_tag") and not play.get("sharp_money_evaluated_at"):
            play["sharp_money_evaluated_at"] = now.isoformat()
    return updated


def summarize_sharp_money(ledger: dict[str, Any]) -> dict[str, Any]:
    """Graded side/total plays split by sharp_money_tag."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "with_sharps": [],
        "against_sharps": [],
        "no_signal": [],
        "no_data": [],
    }
    for p in ledger.get("plays") or []:
        if str(p.get("status") or "") not in ("win", "loss", "push"):
            continue
        if p.get("play_type") == "prop":
            continue
        key = str(p.get("sharp_money_tag") or "no_data")
        buckets.setdefault(key, []).append(p)

    def rec(subset: list[dict[str, Any]]) -> dict[str, Any]:
        w = sum(1 for p in subset if p.get("status") == "win")
        l = sum(1 for p in subset if p.get("status") == "loss")
        pu = sum(1 for p in subset if p.get("status") == "push")
        units = sum(float(p.get("pnl_units") or 0) for p in subset)
        return {"n": len(subset), "record": f"{w}-{l}-{pu}", "units": round(units, 2)}

    return {k: rec(v) for k, v in buckets.items() if v}
