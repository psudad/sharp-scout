"""Phase 4 — Sharp market & split validation filter (RLM, money vs tickets, steam timing)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.phase3.market import EdgeCandidate

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    passed: bool
    notes: list[str] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)
    tier: str = "candidate"  # candidate | lean | play | rejected


def _find_split_game(
    splits: list[dict[str, Any]],
    home: str,
    away: str,
    *,
    sport: str = "nfl",
) -> dict[str, Any] | None:
    from sharp_scout.utils.teams import normalize_ncaaf

    def norm(team: str) -> str:
        if (sport or "nfl").lower() == "ncaaf":
            return normalize_ncaaf(team)
        from sharp_scout.utils.odds import normalize_team

        return normalize_team(team, sport)

    nh, na = norm(home), norm(away)
    for g in splits:
        gh, ga = norm(str(g.get("home_team") or "")), norm(str(g.get("away_team") or ""))
        if gh == nh and ga == na:
            return g
        if gh == na and ga == nh:
            return g
    return None


def money_ticket_gap_ok(
    market_block: dict[str, Any],
    side: str,
    gap_threshold: float,
) -> tuple[bool, str]:
    """Handle % exceeds ticket % by >= gap on our side."""
    if side in ("home", "away"):
        bet = market_block.get(f"{side}_bet_pct")
        money = market_block.get(f"{side}_money_pct")
    elif side in ("over", "under"):
        bet = market_block.get(f"{side}_bet_pct")
        money = market_block.get(f"{side}_money_pct")
    else:
        return False, "unknown side for splits"

    if bet is None or money is None:
        return False, "splits incomplete (money/ticket % missing — run scripts/diagnose_action_network.py)"

    gap = money - bet
    if gap >= gap_threshold:
        return True, f"money-ticket gap +{gap:.0%} on {side} (money={money:.0%} tickets={bet:.0%})"
    return False, f"money-ticket gap only {gap:.0%} on {side} (need ≥{gap_threshold:.0%})"


def reverse_line_movement(
    market_block: dict[str, Any],
    side: str,
    market: str,
) -> tuple[bool, str]:
    """RLM: line moves against the public ticket majority toward our side."""
    open_line = market_block.get("open_line")
    cur_line = market_block.get("current_line")
    if open_line is None or cur_line is None:
        return False, "no open/current line for RLM"

    try:
        open_line = float(open_line)
        cur_line = float(cur_line)
    except (TypeError, ValueError):
        return False, "non-numeric line history"

    if market == "spreads":
        # Lines stored as home spread (negative = home favored)
        public_home = market_block.get("home_bet_pct")
        public_away = market_block.get("away_bet_pct")
        if public_home is None or public_away is None:
            return False, "no ticket % for RLM"
        public_side = "home" if public_home >= public_away else "away"
        # Line moved toward home if cur < open (home getting more points / more favored)
        moved_toward_home = cur_line < open_line
        moved_toward_away = cur_line > open_line
        if abs(cur_line - open_line) < 0.25:
            return False, f"line flat ({open_line}→{cur_line})"

        # RLM if public on home but line moved toward away, etc.
        if public_side == "home" and moved_toward_away and side == "away":
            return True, f"RLM: public {public_home:.0%} home but line {open_line}→{cur_line} toward away"
        if public_side == "away" and moved_toward_home and side == "home":
            return True, f"RLM: public {public_away:.0%} away but line {open_line}→{cur_line} toward home"
        return False, f"no RLM (public={public_side}, line {open_line}→{cur_line})"

    if market == "totals":
        public_over = market_block.get("over_bet_pct")
        public_under = market_block.get("under_bet_pct")
        if public_over is None or public_under is None:
            return False, "no ticket % for totals RLM"
        public_side = "over" if public_over >= public_under else "under"
        moved_up = cur_line > open_line
        moved_down = cur_line < open_line
        if abs(cur_line - open_line) < 0.25:
            return False, f"total flat ({open_line}→{cur_line})"
        if public_side == "over" and moved_down and side == "under":
            return True, f"RLM: public over but total {open_line}→{cur_line}"
        if public_side == "under" and moved_up and side == "over":
            return True, f"RLM: public under but total {open_line}→{cur_line}"
        return False, f"no totals RLM (public={public_side}, {open_line}→{cur_line})"

    return False, "RLM not applicable to h2h without line"


def h2h_outlier_check(edge: EdgeCandidate) -> tuple[bool, str]:
    """Reject moneyline edges that are almost always stale or non-actionable."""
    if edge.market != "h2h":
        return True, ""

    settings = get_settings()

    if edge.edge > settings.max_h2h_edge:
        return (
            False,
            f"h2h EV {edge.edge:.1%} exceeds {settings.max_h2h_edge:.0%} cap (likely stale retail price)",
        )

    if edge.price > settings.max_h2h_plus_price:
        return (
            False,
            f"h2h price {edge.price:+.0f} exceeds +{settings.max_h2h_plus_price:.0f} cap",
        )

    if (
        edge.price >= settings.h2h_dog_price_tight_spread_floor
        and abs(edge.model_spread) < settings.h2h_tight_spread_threshold
    ):
        return (
            False,
            f"model spread {edge.model_spread:+.1f} vs h2h {edge.price:+.0f} "
            f"(pick'em-ish model with extreme ML — likely bad book)",
        )

    return True, ""


def validate_edge(
    edge: EdgeCandidate,
    splits: list[dict[str, Any]],
    require_confirmation: bool = True,
) -> FilterResult:
    """Sanity-check model edge with market structure signals before surfacing a play."""
    settings = get_settings()
    notes: list[str] = []
    flags: dict[str, bool] = {
        "ev_ok": edge.edge >= settings.ev_threshold,
        "rlm": False,
        "money_split": False,
        "vs_sharp": edge.p_mkt is not None and abs(edge.p_true - (edge.p_mkt or 0)) >= 0.015,
        "h2h_sane": True,
    }
    notes.append(f"EV={edge.edge:.2%} at {edge.book} {edge.price:+.0f}")

    ok_h2h, h2h_note = h2h_outlier_check(edge)
    flags["h2h_sane"] = ok_h2h
    if not ok_h2h:
        notes.append(h2h_note)
        return FilterResult(passed=False, notes=notes, flags=flags, tier="rejected")

    game = _find_split_game(splits, edge.home_team, edge.away_team)
    if game is None:
        notes.append("no Action Network split row matched")
        if require_confirmation:
            return FilterResult(passed=False, notes=notes, flags=flags, tier="rejected")
        return FilterResult(passed=True, notes=notes, flags=flags, tier="lean")

    mkey = {"spreads": "spread", "totals": "total", "h2h": "moneyline"}.get(edge.market, edge.market)
    block = (game.get("markets") or {}).get(mkey) or {}

    ok_gap, gap_note = money_ticket_gap_ok(block, edge.side, settings.money_ticket_gap)
    flags["money_split"] = ok_gap
    notes.append(gap_note)

    ok_rlm, rlm_note = reverse_line_movement(block, edge.side, edge.market)
    flags["rlm"] = ok_rlm
    notes.append(rlm_note)

    # Steam: sharp line velocity across books (from timestamped line history).
    ok_steam = False
    try:
        from sharp_scout.phase4.steam import steam_signal

        steam = steam_signal(edge.event_id, edge.market, edge.side)
        ok_steam = bool(steam.get("steam"))
        if ok_steam or steam.get("n_books"):
            notes.append(steam.get("note") or "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("steam check skipped: %s", exc)
    flags["steam"] = ok_steam

    confirmed = flags["money_split"] or flags["rlm"] or flags["steam"]
    if not flags["ev_ok"]:
        return FilterResult(passed=False, notes=notes, flags=flags, tier="rejected")

    if require_confirmation and not confirmed:
        return FilterResult(
            passed=False,
            notes=notes + ["edge lacks RLM / money-ticket / steam confirmation"],
            flags=flags,
            tier="rejected",
        )

    n_confirms = sum(1 for k in ("money_split", "rlm", "steam") if flags[k])
    if n_confirms >= 2 and edge.edge >= 0.03:
        tier = "play"
    elif confirmed:
        tier = "play" if edge.edge >= 0.025 else "lean"
    else:
        tier = "lean"

    return FilterResult(passed=True, notes=notes, flags=flags, tier=tier)


def attach_filters(
    edges: list[EdgeCandidate],
    splits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in edges:
        fr = validate_edge(e, splits)
        out.append(
            {
                "event_id": e.event_id,
                "home_team": e.home_team,
                "away_team": e.away_team,
                "market": e.market,
                "side": e.side,
                "line": e.line,
                "book": e.book,
                "price": e.price,
                "p_true": round(e.p_true, 4),
                "p_mkt": round(e.p_mkt, 4) if e.p_mkt is not None else None,
                "edge": round(e.edge, 4),
                "model_spread": round(e.model_spread, 2),
                "model_total": round(e.model_total, 2),
                "sharp_book": e.sharp_book,
                "sharp_price": e.sharp_price,
                "filter_passed": fr.passed,
                "tier": fr.tier,
                "flags": fr.flags,
                "filter_notes": fr.notes,
                "rationale": "; ".join(fr.notes),
            }
        )
    return out