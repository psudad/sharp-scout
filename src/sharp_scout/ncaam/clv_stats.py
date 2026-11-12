"""Price-aware closing-line stats for the NCAAM board (Pinnacle no-vig at our line)."""

from __future__ import annotations

from typing import Any

from sharp_scout.data import line_store
from sharp_scout.ncaam.rules import RULES
from sharp_scout.phase3.market import fair_probs_from_two_way, shift_prob_to_line
from sharp_scout.utils.odds import expected_value

_PINNACLE = frozenset({"pinnacle"})


def _pinnacle_closing(
    play: dict[str, Any],
    market: str,
    side: str,
    *,
    history: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, Any] | None:
    kickoff = play.get("tip") or play.get("kickoff")
    sample = line_store.closing_sample(
        play.get("event_id"),
        market,
        side,
        kickoff=kickoff,
        history=history,
    )
    if not sample:
        book = str(play.get("close_book") or "").lower()
        if book not in _PINNACLE and play.get("side") == side:
            return None
        if book in _PINNACLE and play.get("side") == side and play.get("close_price") is not None:
            return {
                "line": play.get("close_line"),
                "price": play.get("close_price"),
                "book": play.get("close_book"),
                "ts": play.get("clv_at"),
            }
        return None
    if str(sample.get("book") or "").lower() not in _PINNACLE:
        return None
    return sample


def pinnacle_fair_prob_at_bet_line(
    play: dict[str, Any],
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
    margin_sd: float | None = None,
) -> float | None:
    """Pinnacle no-vig fair cover/win probability at lock, shifted to our bet line."""
    market = str(play.get("market") or "")
    side = str(play.get("side") or "")
    if side not in ("home", "away"):
        return None
    sd = margin_sd if margin_sd is not None else RULES.margin_sd

    if market == "h2h":
        home = _pinnacle_closing(play, "h2h", "home", history=history)
        away = _pinnacle_closing(play, "h2h", "away", history=history)
        if not home or not away:
            return None
        try:
            p_home, p_away = fair_probs_from_two_way(float(home["price"]), float(away["price"]))
        except (TypeError, ValueError):
            return None
        return p_home if side == "home" else p_away

    if market == "spreads":
        bet_line = play.get("line")
        if bet_line is None:
            return None
        home = _pinnacle_closing(play, "spreads", "home", history=history)
        away = _pinnacle_closing(play, "spreads", "away", history=history)
        if not home or not away or home.get("line") is None:
            return None
        try:
            home_line = float(home["line"])
            p_home_fair, _ = fair_probs_from_two_way(float(home["price"]), float(away["price"]))
        except (TypeError, ValueError):
            return None
        p_side = p_home_fair if side == "home" else 1.0 - p_home_fair
        ref = home_line if side == "home" else -home_line
        p_at_line, _ = shift_prob_to_line(
            p_side,
            market="spreads",
            side=side,
            ref_line=ref,
            line=float(bet_line),
            sd=sd,
        )
        return p_at_line

    return None


def ev_at_close(
    play: dict[str, Any],
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
    margin_sd: float | None = None,
) -> float | None:
    """EV of our locked price vs Pinnacle no-vig close at our line (fraction of stake)."""
    price = play.get("price")
    if price is None:
        return None
    p_close = pinnacle_fair_prob_at_bet_line(play, history=history, margin_sd=margin_sd)
    if p_close is None:
        return None
    try:
        return round(expected_value(float(p_close), float(price)), 4)
    except (TypeError, ValueError):
        return None


def summarize_line_beat_close(plays: list[dict[str, Any]]) -> dict[str, Any]:
    """Legacy spread line-only beat close (clv_points > 0), for side-by-side display."""
    vals = [
        float(p["clv_points"])
        for p in plays
        if p.get("clv_points") is not None
    ]
    n = len(vals)
    beat = sum(1 for v in vals if v > 0)
    return {
        "beat_close_pct": round(beat / n, 3) if n else None,
        "beat_close_record": f"{beat}-{n - beat}" if n else None,
        "n_beat_close": n,
    }


def summarize_price_aware_beat_close(
    plays: list[dict[str, Any]],
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
    margin_sd: float | None = None,
) -> dict[str, Any]:
    """Aggregate price-aware beat-close: share with EV at Pinnacle close > 0."""
    evs: list[float] = []
    beat = 0
    for p in plays:
        ev = ev_at_close(p, history=history, margin_sd=margin_sd)
        if ev is None:
            continue
        evs.append(ev)
        if ev > 0:
            beat += 1
    n = len(evs)
    avg = round(sum(evs) / n, 4) if n else None
    line_only = summarize_line_beat_close(plays)
    return {
        "beat_close_pct": round(beat / n, 3) if n else None,
        "beat_close_record": f"{beat}-{n - beat}" if n else None,
        "n_beat_close": n,
        "avg_ev_at_close": avg,
        "line_only_beat_close_pct": line_only.get("beat_close_pct"),
        "line_only_beat_close_record": line_only.get("beat_close_record"),
        "line_only_n_beat_close": line_only.get("n_beat_close"),
    }
