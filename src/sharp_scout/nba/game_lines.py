"""NBA game-line price scanner — EV vs sharp fair, no power model."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.nba.fair import fair_prob_at_line, fair_reference
from sharp_scout.nba.staking import stake_units
from sharp_scout.sports import NBA
from sharp_scout.utils.odds import expected_value

logger = logging.getLogger(__name__)


@dataclass
class GameLineEdge:
    event_id: str
    home_team: str
    away_team: str
    market: str
    side: str
    line: float | None
    book: str
    price: float
    p_true: float
    p_fair: float
    edge: float
    fair_source: str
    fair_book: str | None
    line_gain: float | None
    units: float


def scan_game_line_opportunities(event: dict[str, Any]) -> list[dict[str, Any]]:
    """All retail lines with positive EV and qualification metadata (same odds snapshot)."""
    settings = get_settings()
    thr = settings.nba_ev_threshold
    retail_order = [settings.nba_primary_retail_book, settings.nba_secondary_retail_book]
    books = event.get("bookmakers") or {}
    opportunities: list[dict[str, Any]] = []

    for market in ("spreads", "totals", "h2h"):
        ref = fair_reference(event, market, min_books=2)
        if not ref:
            continue
        sd = NBA.margin_sd if market == "spreads" else NBA.total_sd

        for book_key in retail_order:
            bm = books.get(book_key)
            if not bm:
                continue
            outcomes = (bm.get("markets") or {}).get(market) or []
            for o in outcomes:
                price = o.get("price")
                if price is None:
                    continue
                side = str(o.get("side")).lower()
                line = o.get("point")
                p_fair, line_gain, fair_book = fair_prob_at_line(
                    ref, market=market, side=side, line=float(line) if line is not None else None, sd=sd
                )
                if p_fair is None:
                    continue
                p_true = float(p_fair)
                edge = expected_value(p_true, float(price))
                if edge <= 0:
                    continue
                units = stake_units(p_true, float(price), play_type="side")
                reasons: list[str] = []
                qualified = True
                if edge < thr:
                    qualified = False
                    reasons.append(f"EV below {thr * 100:.1f}% floor")
                if units <= 0:
                    qualified = False
                    reasons.append("Kelly size below minimum")
                opportunities.append(
                    {
                        "event_id": str(event.get("event_id")),
                        "home_team": event["home_team"],
                        "away_team": event["away_team"],
                        "play_type": "side",
                        "market": market,
                        "side": side,
                        "line": float(line) if line is not None else None,
                        "book": book_key,
                        "price": float(price),
                        "p_true": round(p_true, 4),
                        "p_fair": round(p_true, 4),
                        "p_mkt": round(p_true, 4),
                        "edge": round(edge, 4),
                        "units": units,
                        "fair_source": str(ref.get("source") or ref.get("book")),
                        "sharp_book": fair_book,
                        "line_gain": line_gain,
                        "qualified": qualified,
                        "reject_reason": "; ".join(reasons) if reasons else None,
                    }
                )

    return opportunities


def discover_game_line_edges(event: dict[str, Any]) -> list[GameLineEdge]:
    settings = get_settings()
    retail_order = [settings.nba_primary_retail_book, settings.nba_secondary_retail_book]
    edges: list[GameLineEdge] = []
    for row in scan_game_line_opportunities(event):
        if not row.get("qualified"):
            continue
        edges.append(
            GameLineEdge(
                event_id=row["event_id"],
                home_team=row["home_team"],
                away_team=row["away_team"],
                market=row["market"],
                side=row["side"],
                line=row["line"],
                book=row["book"],
                price=row["price"],
                p_true=row["p_true"],
                p_fair=row["p_fair"],
                edge=row["edge"],
                fair_source=row["fair_source"],
                fair_book=row.get("sharp_book"),
                line_gain=row.get("line_gain"),
                units=row["units"],
            )
        )

    best: dict[tuple[str, str], GameLineEdge] = {}
    for e in edges:
        k = (e.market, e.side)
        prev = best.get(k)
        if prev is None or e.edge > prev.edge or (e.edge == prev.edge and e.book == retail_order[0]):
            best[k] = e
    return sorted(best.values(), key=lambda x: x.edge, reverse=True)


def game_line_edge_to_signal(edge: GameLineEdge, *, kickoff: Any) -> dict[str, Any]:
    return {
        "event_id": edge.event_id,
        "sport": "nba",
        "kickoff": kickoff,
        "away_team": edge.away_team,
        "home_team": edge.home_team,
        "play_type": "side",
        "market": edge.market,
        "side": edge.side,
        "line": edge.line,
        "book": edge.book,
        "price": edge.price,
        "units": edge.units,
        "tier": "paper",
        "edge": edge.edge,
        "p_true": edge.p_true,
        "p_mkt": edge.p_fair,
        "p_fair": edge.p_fair,
        "fair_source": edge.fair_source,
        "sharp_book": edge.fair_book,
        "line_gain": edge.line_gain,
        "filter_passed": True,
        "pipeline": "nba_shadow",
        "status": "paper",
    }
