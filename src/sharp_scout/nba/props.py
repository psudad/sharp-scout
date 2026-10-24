"""NBA player prop edges — projection vs consensus, retail price scan."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from scipy.stats import norm

from sharp_scout.config import get_settings
from sharp_scout.nba.fair import prop_consensus_over_prob
from sharp_scout.nba.projections import PlayerRateRow, load_rate_table, project_mean, projected_minutes
from sharp_scout.nba.staking import stake_units
from sharp_scout.phase3.market import anchor_probability, fair_probs_from_two_way
from sharp_scout.utils.odds import expected_value

logger = logging.getLogger(__name__)

BLOCKED_MARKET_SUBSTRINGS = (
    "first_basket",
    "first_field_goal",
    "opening_tip",
    "tip",
)


@dataclass
class PropEdge:
    event_id: str
    home_team: str
    away_team: str
    player_name: str
    market: str
    side: str
    line: float
    book: str
    price: float
    p_true: float
    p_mkt: float | None
    edge: float
    model_mean: float | None
    units: float
    is_alternate: bool = False


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


def _p_over_from_mean(mean: float, line: float, *, cv: float = 0.28) -> float:
    sd = max(mean * cv, 1.5 if mean > 20 else 0.8)
    z = (line + 0.5 - mean) / sd  # continuity correction for integer stats
    return float(1.0 - norm.cdf(z))


def _should_skip_prop(
    *,
    market: str,
    side: str,
    player: str,
    line: float,
    is_alternate: bool,
    row: PlayerRateRow | None,
    table: dict[str, PlayerRateRow],
) -> str | None:
    settings = get_settings()
    ml = market.lower()
    for bad in BLOCKED_MARKET_SUBSTRINGS:
        if bad in ml:
            return f"blocked_market:{bad}"
    if row is None:
        return "no_projection"
    mins = projected_minutes(row, table)
    if side == "under" and mins < settings.nba_prop_min_projected_minutes:
        return "under_low_minutes"
    if is_alternate and side == "under":
        return "alt_under"
    return None


def _consensus_only_edge(
    event: dict[str, Any],
    *,
    market: str,
    player_name: str,
    line: float,
    side: str,
    book_key: str,
    price: float,
) -> tuple[float | None, float | None, str | None]:
    """Fair = de-vig consensus excluding the retail book being graded."""
    p_over = prop_consensus_over_prob(
        event,
        market,
        player_name,
        line,
        exclude_books={book_key},
    )
    if p_over is None:
        return None, None, "consensus_unavailable"
    p_true = float(p_over if side == "over" else 1.0 - p_over)
    edge = expected_value(p_true, price)
    return p_true, edge, None


def scan_prop_opportunities(
    event: dict[str, Any],
    *,
    rates: dict[str, PlayerRateRow] | None = None,
    file_rate_keys: set[str] | None = None,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    table = rates if rates is not None else load_rate_table()
    if file_rate_keys is None:
        file_rate_keys = set(table.keys())
    thr_base = settings.nba_prop_ev_threshold
    retail_order = [settings.nba_primary_retail_book, settings.nba_secondary_retail_book]
    books = event.get("bookmakers") or {}

    line_counts: dict[tuple[str, str], dict[float, int]] = {}
    for bm in books.values():
        for market, outcomes in (bm.get("markets") or {}).items():
            if not str(market).startswith("player_"):
                continue
            if market not in settings.nba_prop_market_list:
                continue
            for o in outcomes:
                player = o.get("description") or o.get("player") or ""
                pt = o.get("point")
                if pt is None:
                    continue
                key = (_norm(player), market)
                ln = float(pt)
                line_counts.setdefault(key, {})
                line_counts[key][ln] = line_counts[key].get(ln, 0) + 1
    main_line: dict[tuple[str, str], float] = {}
    for key, counts in line_counts.items():
        main_line[key] = max(counts.items(), key=lambda x: x[1])[0]

    opportunities: list[dict[str, Any]] = []
    for book_key in retail_order:
        bm = books.get(book_key)
        if not bm:
            continue
        for market, outcomes in (bm.get("markets") or {}).items():
            if market not in settings.nba_prop_market_list:
                continue
            paired: dict[tuple[str, float], dict[str, Any]] = {}
            for o in outcomes:
                player = o.get("description") or o.get("player") or o.get("name") or ""
                side = str(o.get("side") or o.get("name") or "").lower()
                if side not in ("over", "under") or o.get("point") is None or o.get("price") is None:
                    continue
                paired.setdefault((_norm(player), float(o["point"])), {})[side] = o

            for (pk, ln), sides in paired.items():
                if "over" not in sides or "under" not in sides:
                    continue
                player_name = sides["over"].get("description") or sides["over"].get("player") or pk
                is_alt = main_line.get((pk, market), ln) != ln
                file_backed = pk in file_rate_keys
                row = table.get(pk) if file_backed else None

                for side in ("over", "under"):
                    o = sides[side]
                    price = float(o["price"])
                    mean: float | None = None
                    edge_mode = "consensus_only"

                    if file_backed:
                        edge_mode = "model"
                        skip = _should_skip_prop(
                            market=market,
                            side=side,
                            player=player_name,
                            line=ln,
                            is_alternate=is_alt,
                            row=row,
                            table=table,
                        )
                        if skip:
                            continue
                        mean = project_mean(row, market, table) if row else None
                        if mean is None:
                            continue
                        p_model = _p_over_from_mean(mean, ln)
                        if side == "under":
                            p_model = 1.0 - p_model
                        p_mkt = prop_consensus_over_prob(event, market, player_name, ln)
                        if p_mkt is not None and side == "under":
                            p_mkt = 1.0 - p_mkt
                        elif p_mkt is None:
                            fo, fu = fair_probs_from_two_way(
                                float(sides["over"]["price"]), float(sides["under"]["price"])
                            )
                            p_mkt = fo if side == "over" else fu
                        p_true = anchor_probability(p_model, p_mkt, k=0.35, cap=0.08)
                        edge = expected_value(p_true, price)
                    else:
                        p_true, edge, skip = _consensus_only_edge(
                            event,
                            market=market,
                            player_name=str(player_name),
                            line=ln,
                            side=side,
                            book_key=book_key,
                            price=price,
                        )
                        if skip:
                            if stats is not None and skip == "consensus_unavailable":
                                stats["consensus_unavailable"] = stats.get("consensus_unavailable", 0) + 1
                            continue
                        p_mkt = float(p_true)
                        if stats is not None:
                            stats["consensus_only_scored"] = stats.get("consensus_only_scored", 0) + 1
                        if edge is None or p_true is None:
                            continue

                    thr = thr_base + (settings.nba_prop_over_extra_ev if side == "over" else 0.0)
                    if edge <= 0:
                        continue
                    units = stake_units(float(p_true), price, play_type="prop")
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
                            "play_type": "prop",
                            "player_name": str(player_name),
                            "market": market,
                            "side": side,
                            "line": ln,
                            "book": book_key,
                            "price": price,
                            "p_true": round(float(p_true), 4),
                            "p_mkt": round(float(p_mkt), 4) if p_mkt is not None else None,
                            "edge": round(edge, 4),
                            "model_mean": round(mean, 2) if mean is not None else None,
                            "units": units,
                            "is_alternate": is_alt,
                            "qualified": qualified,
                            "reject_reason": "; ".join(reasons) if reasons else None,
                            "edge_mode": edge_mode,
                            "fair_source": "consensus_ex_retail" if edge_mode == "consensus_only" else "model",
                        }
                    )
                    if stats is not None:
                        if edge_mode == "model":
                            stats["model_scored"] = stats.get("model_scored", 0) + 1

    return opportunities


def discover_prop_edges(
    event: dict[str, Any],
    *,
    rates: dict[str, PlayerRateRow] | None = None,
    file_rate_keys: set[str] | None = None,
) -> list[PropEdge]:
    edges: list[PropEdge] = []
    for row in scan_prop_opportunities(event, rates=rates, file_rate_keys=file_rate_keys):
        if not row.get("qualified"):
            continue
        edges.append(
            PropEdge(
                event_id=row["event_id"],
                home_team=row["home_team"],
                away_team=row["away_team"],
                player_name=row["player_name"],
                market=row["market"],
                side=row["side"],
                line=row["line"],
                book=row["book"],
                price=row["price"],
                p_true=row["p_true"],
                p_mkt=row["p_mkt"],
                edge=row["edge"],
                model_mean=row.get("model_mean"),
                units=row["units"],
                is_alternate=row.get("is_alternate", False),
            )
        )

    best: dict[tuple[str, str, str, float], PropEdge] = {}
    for e in edges:
        k = (e.player_name.lower(), e.market, e.side, e.line)
        prev = best.get(k)
        if prev is None or e.edge > prev.edge:
            best[k] = e
    return sorted(best.values(), key=lambda x: x.edge, reverse=True)


def prop_edge_to_signal(edge: PropEdge, *, kickoff: Any) -> dict[str, Any]:
    return {
        "event_id": edge.event_id,
        "sport": "nba",
        "kickoff": kickoff,
        "away_team": edge.away_team,
        "home_team": edge.home_team,
        "play_type": "prop",
        "player_name": edge.player_name,
        "market": edge.market,
        "side": edge.side,
        "line": edge.line,
        "book": edge.book,
        "price": edge.price,
        "units": edge.units,
        "tier": "paper",
        "edge": edge.edge,
        "p_true": edge.p_true,
        "p_mkt": edge.p_mkt,
        "model_mean": edge.model_mean,
        "is_alternate": edge.is_alternate,
        "filter_passed": True,
        "pipeline": "nba_shadow",
        "status": "paper",
    }
