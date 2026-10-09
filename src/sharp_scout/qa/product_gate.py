"""Product gate — only plays we would sell or post as LOCKED Sharp Plays.

Phase 4 ``filter_passed`` means the model found EV; this layer means the bet is
structurally defensible (sharp side, corroboration, size cap). ML requires split-board
spread + moneyline sharp confirmation (option B).
Research signals and stage leans are unchanged; only ledger posting uses certified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.qa.gate import _count_books_on_market, _split_board
from sharp_scout.utils.odds import american_to_implied_prob

SHADOW_MARKET_NOTE = "shadow market"


def shadow_markets(settings: Any | None = None) -> set[str]:
    s = settings or get_settings()
    return {m.strip() for m in (s.product_shadow_markets or "").split(",") if m.strip()}


def is_shadow_only(reasons: tuple[str, ...] | list[str]) -> bool:
    """True when the only thing keeping a play off the card is its shadow market."""
    return bool(reasons) and all(r.startswith(SHADOW_MARKET_NOTE) for r in reasons)


@dataclass(frozen=True)
class ProductGateResult:
    ok: bool
    reasons: tuple[str, ...] = ()

    def note(self) -> str:
        return "; ".join(self.reasons)


def is_whitelisted(play: dict[str, Any], sport: str, settings: Any | None = None) -> bool:
    """True when (sport, market) is in the configured product whitelist."""
    settings = settings or get_settings()
    if not getattr(settings, "product_whitelist_enabled", False):
        return False
    pairs = {
        tuple(x.strip().lower().split(":", 1))
        for x in (settings.product_whitelist or "").split(",")
        if ":" in x
    }
    return (str(sport).lower(), str(play.get("market") or "").lower()) in pairs


def _p_fair(signal: dict[str, Any]) -> float | None:
    pf = signal.get("p_fair")
    if pf is not None:
        return float(pf)
    pm = signal.get("p_mkt")
    if pm is not None:
        return float(pm)
    return None


def _ml_ticket_gap_min(settings: Any) -> float:
    gap = settings.product_ml_ticket_gap
    if gap is not None:
        return float(gap)
    return float(settings.money_ticket_gap)


def _check_ml_split_board_confirmation(
    play: dict[str, Any],
    signals: dict[str, Any],
    *,
    settings: Any,
) -> list[str]:
    """Option B: ML only when spread sharp money and ML ticket gap agree with our side."""
    reasons: list[str] = []
    side = str(play.get("side") or "")
    gap_min = _ml_ticket_gap_min(settings)

    sb = _split_board(signals, play)
    if sb is None:
        if settings.product_ml_require_split_board:
            reasons.append("no split-board data for ML confirmation")
        return reasons

    if not sb.get("available") and settings.product_ml_require_split_board:
        reasons.append("split-board unavailable for this game")

    markets = sb.get("markets") or {}
    if settings.product_ml_require_spread_sharp_align:
        spread = markets.get("spread") or {}
        se = spread.get("sharp_edge") or {}
        se_gap = float(se.get("diff_pct") or 0)
        se_side = se.get("side")
        if not se.get("available"):
            reasons.append("spread sharp money signal unavailable")
        elif se_side != side:
            team = se.get("team") or se_side
            reasons.append(
                f"spread sharp money on {team} (+{se_gap:.0%}) conflicts with ML {side}"
            )
        elif se_gap < gap_min:
            reasons.append(
                f"spread money-ticket gap +{se_gap:.0%} < {gap_min:.0%} required for ML"
            )

    if settings.product_ml_require_ml_ticket_gap:
        ml = markets.get("moneyline") or {}
        ml_se = ml.get("sharp_edge") or {}
        ml_gap = float(ml_se.get("diff_pct") or 0)
        ml_side = ml_se.get("side")
        if not ml_se.get("available"):
            reasons.append("ML sharp money signal unavailable")
        elif ml_side and ml_side != side:
            team = ml_se.get("team") or ml_side
            reasons.append(f"ML handle favors {team} (+{ml_gap:.0%}), not our {side} side")
        elif ml_gap < gap_min:
            reasons.append(
                f"ML money-ticket gap +{ml_gap:.0%} < {gap_min:.0%} required for certified ML"
            )

    return reasons


def _check_total_sharp_confirmation(
    play: dict[str, Any],
    signals: dict[str, Any],
    *,
    settings: Any,
) -> list[str]:
    """Totals must not fight the sharp-money read.

    A total is only certified when it does NOT run into money on the other side. We reject
    when (a) sharp money (handle-minus-tickets) sits on the opposite side, (b) both tickets
    and handle majorities are on the opposite side, or (c) the model total is far off the
    market line without any money confirmation on our side. RLM alone is not enough.
    """
    reasons: list[str] = []
    side = str(play.get("side") or "")
    if side not in ("over", "under"):
        return reasons
    opp = "over" if side == "under" else "under"

    sb = _split_board(signals, play)
    total = None
    if sb and sb.get("available"):
        total = (sb.get("markets") or {}).get("total")

    confirmed = False
    if total:
        se = total.get("sharp_edge") or {}
        se_side = se.get("side")
        se_gap = float(se.get("diff_pct") or 0)
        if se.get("available") and se_side == side and se_gap >= settings.product_total_money_gap:
            confirmed = True
        if se.get("available") and se_side == opp and se_gap >= settings.product_total_opposing_gap:
            reasons.append(
                f"total sharp money on {opp} (+{se_gap:.0%}) opposes our {side} — RLM not enough"
            )

        sides = total.get("sides") or {}
        our = sides.get(side) or {}
        their = sides.get(opp) or {}
        our_t, our_m = our.get("tickets_pct"), our.get("money_pct")
        their_t, their_m = their.get("tickets_pct"), their.get("money_pct")
        if (
            None not in (our_t, our_m, their_t, their_m)
            and their_t > our_t
            and their_m > our_m
        ):
            reasons.append(
                f"both tickets ({their_t:.0%}) and handle ({their_m:.0%}) favor {opp}, not our {side}"
            )

    model_total = play.get("model_total")
    line = play.get("line")
    if model_total is not None and line is not None:
        gap = abs(float(model_total) - float(line))
        if gap > settings.product_total_model_market_max_gap and not confirmed:
            reasons.append(
                f"model total off market by {gap:.1f} pts "
                f"(>{settings.product_total_model_market_max_gap:.0f}) without sharp-money confirmation"
            )

    return reasons


def evaluate_product_play(
    play: dict[str, Any],
    *,
    signals: dict[str, Any] | None = None,
    sport: str = "nfl",
) -> ProductGateResult:
    """Return whether this signal/play is eligible for the public LOCKED card."""
    settings = get_settings()
    if not settings.product_gate_enabled:
        return ProductGateResult(True, ())

    reasons: list[str] = []
    market = str(play.get("market") or "")
    allowed = {m.strip() for m in settings.product_markets.split(",") if m.strip()}
    if market not in allowed:
        reasons.append(f"market {market} not in product set ({','.join(sorted(allowed))})")

    if settings.product_play_tier_only and (play.get("tier") or "") != "play":
        reasons.append(f"tier={play.get('tier') or 'lean'} (product requires play)")

    edge = play.get("edge")
    if edge is None:
        reasons.append("missing edge")
    else:
        wl = is_whitelisted(play, sport, settings)
        ev_min = settings.product_whitelist_ev_min if wl else settings.product_ev_min
        if float(edge) < ev_min:
            reasons.append(f"EV {float(edge):.1%} < {ev_min:.0%} product floor")
        ev_max = settings.product_ev_max
        if not wl and ev_max is not None and float(edge) >= ev_max:
            reasons.append(
                f"EV {float(edge):.1%} ≥ {ev_max:.0%} product ceiling (model-tilt outlier)"
            )

    pf = _p_fair(play)
    if pf is None:
        reasons.append("missing sharp fair probability (p_fair / p_mkt)")
    elif pf < settings.product_p_fair_min:
        reasons.append(
            f"sharp no-vig {pf:.1%} on our side < {settings.product_p_fair_min:.0%} floor"
        )

    price = play.get("price")
    if pf is not None and price is not None:
        value = pf - american_to_implied_prob(float(price))
        if value < settings.product_min_price_vs_fair:
            reasons.append(
                f"price {float(price):+.0f} is {-value:.1%} worse than sharp fair "
                f"(limit {-settings.product_min_price_vs_fair:.0%}) — starts with negative CLV"
            )

    if signals is not None:
        n_books = _count_books_on_market(signals, play)
        waive_single_book_total = (
            market == "totals"
            and settings.qa_promote_single_book_totals
            and n_books >= 1
        )
        if not waive_single_book_total and n_books < settings.product_min_books:
            reasons.append(
                f"only {n_books} book(s) on line (need ≥{settings.product_min_books})"
            )

        if market == "h2h":
            reasons.extend(_check_ml_split_board_confirmation(play, signals, settings=settings))

        if market == "totals" and settings.product_total_sharp_guardrail:
            reasons.extend(_check_total_sharp_confirmation(play, signals, settings=settings))

    if market in shadow_markets(settings):
        reasons.append(f"{SHADOW_MARKET_NOTE}: {market} is tracked on the watchlist, not posted")

    if reasons:
        return ProductGateResult(False, tuple(reasons))
    return ProductGateResult(True, ())


def select_certified_plays(
    candidates: list[dict[str, Any]],
    *,
    signals: dict[str, Any],
    sport: str = "nfl",
) -> list[dict[str, Any]]:
    """Filter and cap plays for ledger posting (ranked by edge)."""
    settings = get_settings()
    passed: list[dict[str, Any]] = []
    for s in candidates:
        if not s.get("filter_passed"):
            continue
        res = evaluate_product_play(s, signals=signals, sport=sport)
        s["product_certified"] = res.ok
        s["product_gate_notes"] = list(res.reasons) if res.reasons else []
        if res.ok:
            passed.append(s)

    # Whitelisted sport:market pairs rank first, then by edge.
    passed.sort(
        key=lambda x: (is_whitelisted(x, sport, settings), float(x.get("edge") or 0)),
        reverse=True,
    )

    cap = (
        settings.product_max_plays_ncaaf
        if sport == "ncaaf"
        else settings.product_max_plays_nfl
    )

    return _best_per_event_market(passed, cap=cap)


def select_shadow_plays(
    candidates: list[dict[str, Any]],
    *,
    signals: dict[str, Any],
    sport: str = "nfl",
) -> list[dict[str, Any]]:
    """Plays that would certify except for being in a shadow market (watchlist tracking)."""
    passed: list[dict[str, Any]] = []
    for s in candidates:
        if not s.get("filter_passed") or s.get("market") not in shadow_markets():
            continue
        res = evaluate_product_play(s, signals=signals, sport=sport)
        if is_shadow_only(res.reasons):
            s["product_shadow"] = True
            passed.append(s)
    passed.sort(key=lambda x: float(x.get("edge") or 0), reverse=True)
    return _best_per_event_market(passed, cap=None)


def _best_per_event_market(
    plays: list[dict[str, Any]], *, cap: int | None
) -> list[dict[str, Any]]:
    """At most one play per (event, market) — input must already be sorted best-first."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for s in plays:
        key = (str(s.get("event_id")), str(s.get("market")))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if cap is not None and len(out) >= cap:
            break
    return out
