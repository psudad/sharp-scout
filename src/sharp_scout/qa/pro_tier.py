"""Action PRO tier — LOCKED candidates driven by Action Network PRO Report signals.

Backtest (``scripts/backtest_action_pro.py``, 2024-26 closing lines/prices): NCAAF totals
with Sharp Action *and* an Action power-rating edge >= 3 pts on the same side went 97-70
(58.1%) and were profitable in every season. Our own model is not required to agree;
the play is priced at a bettable book against the Pinnacle no-vig fair at that line.
"""

from __future__ import annotations

from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.utils.odds import american_to_implied_prob, expected_value

PRO_TIER_FLAG = "pro_confirmed"

_BOARD_MARKET = {"totals": "total", "spreads": "spread", "h2h": "moneyline"}


def parse_pro_tier_lanes(settings: Any | None = None) -> set[tuple[str, str]]:
    s = settings or get_settings()
    out: set[tuple[str, str]] = set()
    for raw in (s.pro_tier_lanes or "").split(","):
        if ":" in raw:
            sport, market = raw.strip().split(":", 1)
            out.add((sport.strip().lower(), market.strip().lower()))
    return out


def bettable_books(settings: Any | None = None) -> set[str]:
    s = settings or get_settings()
    return {b.strip().lower() for b in (s.product_bettable_books or "").split(",") if b.strip()}


def side_pro_signals(
    board: dict[str, Any] | None, market: str, side: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(our side's PRO signals, opposing side's PRO signals) from a split board."""
    if not board:
        return [], []
    mkt = (board.get("markets") or {}).get(_BOARD_MARKET.get(market, market)) or {}
    sides = mkt.get("sides") or {}
    ours = list((sides.get(side) or {}).get("pro_signals") or [])
    theirs: list[dict[str, Any]] = []
    for other, row in sides.items():
        if other != side:
            theirs.extend((row or {}).get("pro_signals") or [])
    return ours, theirs


def pro_tier_reasons(signals_on_side: list[dict[str, Any]], *, settings: Any | None = None) -> list[str]:
    """Empty when the side carries the backtested PRO combination; else why not."""
    s = settings or get_settings()
    by_type = {str(x.get("type")): x for x in signals_on_side}
    reasons: list[str] = []
    if "sharp_money" not in by_type:
        reasons.append("no Action Sharp Action signal on our side")
    model = by_type.get("power_rating_edge")
    if model is None:
        reasons.append("no Action model (power-rating) edge on our side")
    else:
        edge = float(model.get("edge") or 0)
        if edge < s.pro_tier_min_model_edge:
            reasons.append(
                f"Action model edge {edge:.1f} pts < {s.pro_tier_min_model_edge:.1f} required"
            )
    return reasons


def pro_signal_summary(signals_on_side: list[dict[str, Any]]) -> str:
    parts = []
    for x in signals_on_side:
        t = x.get("type")
        if t == "sharp_money":
            parts.append(
                f"Sharp Action ({x.get('steam_moves') or 0} steam, "
                f"{x.get('reverse_line_moves') or 0} RLM)"
            )
        elif t == "power_rating_edge":
            parts.append(f"Action model edge {float(x.get('edge') or 0):.1f} pts")
        elif t == "big_bets":
            parts.append("Big Money")
        elif t == "pro_systems":
            parts.append("PRO System")
    return " + ".join(parts)


def _fair_at_line(event: dict[str, Any], market: str, side: str, line: float | None, sport: str) -> tuple[float | None, str | None, float | None]:
    """Pinnacle (or next sharp) no-vig prob for ``side``, shifted to ``line``."""
    from sharp_scout.phase3.market import sharp_consensus, shift_prob_to_line
    from sharp_scout.sports import get_sport

    sharp = sharp_consensus(event, market)
    if not sharp:
        return None, None, None
    ref = next((o for o in sharp["outcomes"] if o.get("side") == side), None)
    if ref is None or ref.get("p_mkt") is None:
        return None, sharp.get("book"), None
    cfg = get_sport(sport)
    sd = cfg.margin_sd if market == "spreads" else cfg.total_sd
    p, _gain = shift_prob_to_line(
        float(ref["p_mkt"]), market=market, side=side, ref_line=ref.get("point"), line=line, sd=sd
    )
    return p, sharp.get("book"), (float(ref["price"]) if ref.get("price") is not None else None)


def build_pro_tier_candidates(
    events: list[dict[str, Any]],
    split_boards: list[dict[str, Any]],
    *,
    sport: str,
    game_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Signal rows (Phase-4 shape) for every PRO-tier side priced at a bettable book."""
    settings = get_settings()
    if not settings.pro_tier_enabled:
        return []
    lanes = {m for (sp, m) in parse_pro_tier_lanes(settings) if sp == str(sport).lower()}
    if not lanes:
        return []
    books_ok = bettable_books(settings)
    boards = {(b.get("home_team"), b.get("away_team")): b for b in split_boards or []}
    models = {str(g.get("event_id")): g for g in game_results or []}
    out: list[dict[str, Any]] = []
    for ev in events:
        board = boards.get((ev.get("home_team"), ev.get("away_team")))
        if not board or not board.get("available"):
            continue
        kickoff = ev.get("commence_time")
        kickoff = kickoff.isoformat() if hasattr(kickoff, "isoformat") else kickoff
        game = models.get(str(ev.get("event_id"))) or {}
        for market in sorted(lanes):
            for book_key, bm in (ev.get("bookmakers") or {}).items():
                if books_ok and str(book_key).lower() not in books_ok:
                    continue
                for o in (bm.get("markets") or {}).get(market) or []:
                    side, price, line = o.get("side"), o.get("price"), o.get("point")
                    if side is None or price is None:
                        continue
                    ours, theirs = side_pro_signals(board, market, side)
                    if pro_tier_reasons(ours, settings=settings):
                        continue
                    p_fair, sharp_book, sharp_price = _fair_at_line(ev, market, side, line, sport)
                    if p_fair is None:
                        continue
                    p_true = min(p_fair + settings.pro_tier_prob_lift, 0.99)
                    out.append(
                        {
                            "event_id": str(ev.get("event_id")),
                            "home_team": ev.get("home_team"),
                            "away_team": ev.get("away_team"),
                            "market": market,
                            "side": side,
                            "line": float(line) if line is not None else None,
                            "book": book_key,
                            "price": float(price),
                            "p_true": round(p_true, 4),
                            "p_mkt": round(p_fair, 4),
                            "p_fair": round(p_fair, 4),
                            "p_model": None,
                            "edge": round(expected_value(p_true, float(price)), 4),
                            "sharp_book": sharp_book,
                            "sharp_price": sharp_price,
                            "model_spread": game.get("model_spread"),
                            "model_total": game.get("model_total"),
                            "kickoff": kickoff,
                            "commence_time": kickoff,
                            "sport": sport,
                            "tier": "play",
                            "units": settings.pro_tier_units,
                            "filter_passed": True,
                            "filter_notes": [],
                            "flags": {"pro_tier": True},
                            PRO_TIER_FLAG: True,
                            "high_confidence": True,
                            "pro_signals": ours,
                            "pro_opposing": theirs,
                            "rationale": f"Action PRO tier: {pro_signal_summary(ours)}",
                        }
                    )
    return out


def price_vs_fair(play: dict[str, Any]) -> float | None:
    pf, price = play.get("p_fair"), play.get("price")
    if pf is None or price is None:
        return None
    return float(pf) - american_to_implied_prob(float(price))
