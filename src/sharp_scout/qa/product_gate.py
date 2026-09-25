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


@dataclass(frozen=True)
class ProductGateResult:
    ok: bool
    reasons: tuple[str, ...] = ()

    def note(self) -> str:
        return "; ".join(self.reasons)


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
    elif float(edge) < settings.product_ev_min:
        reasons.append(f"EV {float(edge):.1%} < {settings.product_ev_min:.0%} product floor")

    pf = _p_fair(play)
    if pf is None:
        reasons.append("missing sharp fair probability (p_fair / p_mkt)")
    elif pf < settings.product_p_fair_min:
        reasons.append(
            f"sharp no-vig {pf:.1%} on our side < {settings.product_p_fair_min:.0%} floor"
        )

    if signals is not None:
        n_books = _count_books_on_market(signals, play)
        if n_books < settings.product_min_books:
            reasons.append(
                f"only {n_books} book(s) on line (need ≥{settings.product_min_books})"
            )

        if market == "h2h":
            reasons.extend(_check_ml_split_board_confirmation(play, signals, settings=settings))

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

    passed.sort(key=lambda x: float(x.get("edge") or 0), reverse=True)

    cap = (
        settings.product_max_plays_ncaaf
        if sport == "ncaaf"
        else settings.product_max_plays_nfl
    )

    # At most one certified play per (event, market) — keep best edge.
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for s in passed:
        key = (str(s.get("event_id")), str(s.get("market")))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= cap:
            break
    return out
