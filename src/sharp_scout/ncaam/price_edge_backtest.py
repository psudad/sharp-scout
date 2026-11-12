"""Backtest counters for the NCAAM price-edge gate on ledger history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.data import line_store
from sharp_scout.ncaam.price_edge import price_edge_ev, price_edge_qualifies, wilson_ci
from sharp_scout.ncaam.rules import MODEL_VERSION, RULES
from sharp_scout.phase3.market import fair_probs_from_two_way, shift_prob_to_line
from sharp_scout.utils.odds import expected_value_with_push, win_prob_to_conditional

LEDGER_PATH = DATA_DIR / "ncaam_ledger.json"
LINE_HISTORY_PATH = DATA_DIR / "ncaam" / "line_history.json"


def _is_official_pick(play: dict[str, Any]) -> bool:
    if play.get("model_version") != MODEL_VERSION:
        return False
    if not play.get("side") or play.get("status") in (None, "no_play", "missed", "void"):
        return False
    if float(play.get("units") or 0) <= 0:
        return False
    return play.get("status") in ("win", "loss", "push")


def _pinnacle_close_fair(
    play: dict[str, Any],
    history: dict[str, list[dict[str, Any]]],
) -> float | None:
    """Pinnacle no-vig cover/win prob at our line from the pre-kick close sample."""
    market = str(play.get("market") or "")
    side = str(play.get("side") or "")
    eid = play.get("event_id")
    kickoff = play.get("tip") or play.get("kickoff")
    if market == "h2h":
        home = line_store.closing_sample(eid, "h2h", "home", kickoff=kickoff, history=history)
        away = line_store.closing_sample(eid, "h2h", "away", kickoff=kickoff, history=history)
        if not home or not away:
            return None
        try:
            p_home, p_away = fair_probs_from_two_way(float(home["price"]), float(away["price"]))
        except (TypeError, ValueError, KeyError):
            return None
        return p_home if side == "home" else p_away
    if market != "spreads":
        return None
    home = line_store.closing_sample(eid, "spreads", "home", kickoff=kickoff, history=history)
    away = line_store.closing_sample(eid, "spreads", "away", kickoff=kickoff, history=history)
    if not home or not away or home.get("line") is None:
        return None
    try:
        p_home_fair, _ = fair_probs_from_two_way(float(home["price"]), float(away["price"]))
        ref = float(home["line"])
        line = float(play.get("line"))
    except (TypeError, ValueError, KeyError):
        return None
    p_side, _ = shift_prob_to_line(
        p_home_fair if side == "home" else 1.0 - p_home_fair,
        market="spreads",
        side=side,
        ref_line=ref if side == "home" else -ref,
        line=line,
        sd=RULES.margin_sd,
    )
    return p_side


def price_aware_beat_close(
    play: dict[str, Any],
    history: dict[str, list[dict[str, Any]]],
) -> bool | None:
    """True when EV at the Pinnacle no-vig close (shifted to our line) beats our price."""
    p_close = _pinnacle_close_fair(play, history)
    price = play.get("price")
    if p_close is None or price is None:
        return None
    p_push = float(play.get("p_push") or 0.0)
    if p_push > 0:
        p_cond = win_prob_to_conditional(float(p_close), p_push)
        ev = expected_value_with_push(p_cond, float(price), p_push)
    else:
        from sharp_scout.utils.odds import expected_value

        ev = expected_value(float(p_close), float(price))
    return ev > 0


def _agg(plays: list[dict[str, Any]], *, history: dict[str, list]) -> dict[str, Any]:
    wins = losses = pushes = 0
    units = 0.0
    staked = 0.0
    beat_n = beat_denom = 0
    for p in plays:
        st = str(p.get("status") or "")
        if st == "win":
            wins += 1
        elif st == "loss":
            losses += 1
        elif st == "push":
            pushes += 1
        else:
            continue
        u = float(p.get("units") or 0)
        staked += u
        units += float(p.get("pnl_units") or 0)
        bc = price_aware_beat_close(p, history)
        if bc is not None:
            beat_denom += 1
            if bc:
                beat_n += 1
    n_decided = wins + losses + pushes
    roi = (units / staked) if staked > 0 else 0.0
    ci = wilson_ci(wins, wins + losses) if (wins + losses) else (float("nan"), float("nan"))
    return {
        "n": n_decided,
        "w": wins,
        "l": losses,
        "p": pushes,
        "units": round(units, 2),
        "staked": round(staked, 2),
        "roi_pct": round(100 * roi, 1),
        "wilson_lo": round(100 * ci[0], 1) if n_decided else None,
        "wilson_hi": round(100 * ci[1], 1) if n_decided else None,
        "beat_close": f"{beat_n}/{beat_denom}" if beat_denom else "—",
        "beat_close_pct": round(100 * beat_n / beat_denom, 1) if beat_denom else None,
    }


def run_ledger_backtest(
    *,
    ledger_path: Path | None = None,
    history_path: Path | None = None,
    min_edge: float = 0.01,
) -> dict[str, Any]:
    ledger_path = ledger_path or LEDGER_PATH
    history_path = history_path or LINE_HISTORY_PATH
    ledger = json.loads(ledger_path.read_text())
    try:
        history = json.loads(history_path.read_text())
    except OSError:
        history = {}
    picks = [p for p in ledger.get("plays") or [] if _is_official_pick(p)]
    gated = [
        p
        for p in picks
        if price_edge_qualifies(
            p.get("p_fair"),
            p.get("price"),
            min_edge=min_edge,
            p_push=float(p.get("p_push") or 0.0),
        )
    ]
    return {
        "min_edge": min_edge,
        "all_plays": _agg(picks, history=history),
        "gated_plays": _agg(gated, history=history),
        "gate_skipped_n": len(picks) - len(gated),
    }


def format_backtest_markdown(result: dict[str, Any]) -> str:
    def row(label: str, bucket: dict[str, Any]) -> str:
        wlp = f"{bucket['w']}-{bucket['l']}" + (f"-{bucket['p']}" if bucket["p"] else "")
        wilson = (
            f"{bucket['wilson_lo']}%–{bucket['wilson_hi']}%"
            if bucket.get("wilson_lo") is not None
            else "—"
        )
        bc = bucket["beat_close"]
        if bucket.get("beat_close_pct") is not None:
            bc = f"{bc} ({bucket['beat_close_pct']}%)"
        return (
            f"| {label} | {bucket['n']} | {wlp} | {wilson} | "
            f"{bucket['units']:+.2f} | {bucket['roi_pct']:+.1f}% | {bc} |"
        )

    lines = [
        "### NCAAM ledger backtest (price-edge gate ≥ {:.0%})".format(result["min_edge"]),
        "",
        "| Cohort | n | W-L-P | Win% Wilson 95% | Units | ROI | Beat Pinnacle close (price-aware) |",
        "|---|---|---|---|---|---|---|",
        row("All official plays", result["all_plays"]),
        row("Gate ≥ {:.0%} (price-only EV)".format(result["min_edge"]), result["gated_plays"]),
        "",
        f"Skipped by gate (in-sample): **{result['gate_skipped_n']}** plays.",
    ]
    return "\n".join(lines)
