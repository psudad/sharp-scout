"""Phase 3 — Prop market EV & alternate-line discrepancy engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.phase3.market import fair_probs_from_two_way
from sharp_scout.props.simulate import PropSimResult, p_true_over_under
from sharp_scout.props.usage import PlayerUsage, find_player
from sharp_scout.utils.odds import expected_value

logger = logging.getLogger(__name__)


@dataclass
class PropEdge:
    event_id: str
    home_team: str
    away_team: str
    player_name: str
    team: str
    market: str
    side: str
    line: float | None
    book: str
    price: float
    p_true: float
    p_mkt: float | None
    edge: float
    model_mean: float
    model_median: float
    is_alternate: bool = False


def discover_prop_edges(
    event: dict[str, Any],
    sims: dict[tuple[str, str], PropSimResult],
    *,
    ev_threshold: float | None = None,
    include_alternates: bool = True,
) -> list[PropEdge]:
    """Score offered prop lines against simulated distributions.

    `sims` keyed by (player_key_lower, market).
    """
    settings = get_settings()
    thr = settings.ev_threshold if ev_threshold is None else ev_threshold
    edges: list[PropEdge] = []
    books = event.get("bookmakers") or {}

    # Collect all lines per (player, market) to detect main vs alternate
    line_sets: dict[tuple[str, str], set[float]] = {}
    for bm in books.values():
        for market, outcomes in (bm.get("markets") or {}).items():
            if not str(market).startswith("player_"):
                continue
            for o in outcomes:
                player = o.get("description") or o.get("player") or ""
                point = o.get("point")
                if point is None:
                    continue
                key = (_norm(player), market)
                line_sets.setdefault(key, set()).add(float(point))

    for book_key, bm in books.items():
        for market, outcomes in (bm.get("markets") or {}).items():
            if not str(market).startswith("player_"):
                continue
            # Pair over/under by player+line
            paired: dict[tuple[str, float], dict[str, Any]] = {}
            for o in outcomes:
                player = o.get("description") or o.get("player") or o.get("name") or ""
                side = (o.get("name") or o.get("side") or "").lower()
                if side not in ("over", "under"):
                    # anytime TD etc.
                    if market == "player_anytime_td":
                        side = "yes" if "yes" in side or side == player.lower() else side
                    else:
                        continue
                point = o.get("point")
                price = o.get("price")
                if price is None:
                    continue
                if point is None and market != "player_anytime_td":
                    continue
                line = float(point) if point is not None else 0.5
                paired.setdefault((_norm(player), line), {})[side] = {
                    "player": player,
                    "price": float(price),
                    "line": line if point is not None else None,
                }

            for (pkey, line), sides in paired.items():
                sim = sims.get((pkey, market))
                if sim is None:
                    continue
                # no-vig when both sides present
                fair: dict[str, float] = {}
                if "over" in sides and "under" in sides:
                    fo, fu = fair_probs_from_two_way(sides["over"]["price"], sides["under"]["price"])
                    fair = {"over": fo, "under": fu}

                main_line = _main_line(line_sets.get((pkey, market), {line}))
                is_alt = abs(line - main_line) >= 5.0 if market.endswith("_yds") else abs(line - main_line) >= 1.0
                if not include_alternates and is_alt:
                    continue

                for side, meta in sides.items():
                    if side not in ("over", "under"):
                        continue
                    p_true = p_true_over_under(sim, side, line)
                    p_mkt = fair.get(side)
                    edge = expected_value(p_true, meta["price"])
                    # Tail alts: require slightly higher edge
                    need = thr + (0.015 if is_alt else 0.0)
                    vs_mkt = abs(p_true - p_mkt) if p_mkt is not None else 1.0
                    if edge >= need and vs_mkt >= 0.01:
                        edges.append(
                            PropEdge(
                                event_id=str(event.get("event_id")),
                                home_team=event["home_team"],
                                away_team=event["away_team"],
                                player_name=meta["player"],
                                team=sim.team,
                                market=market,
                                side=side,
                                line=meta["line"],
                                book=book_key,
                                price=meta["price"],
                                p_true=p_true,
                                p_mkt=p_mkt,
                                edge=edge,
                                model_mean=sim.mean,
                                model_median=sim.median,
                                is_alternate=is_alt,
                            )
                        )
    edges.sort(key=lambda e: e.edge, reverse=True)
    return edges


def build_sims_for_event(
    event: dict[str, Any],
    profiles: dict[str, PlayerUsage],
    scripted: dict[str, PlayerUsage],
    markets: list[str],
    n_sims: int | None = None,
) -> dict[tuple[str, str], PropSimResult]:
    from sharp_scout.props.simulate import simulate_prop

    # Determine which players appear in books
    players: set[str] = set()
    for bm in (event.get("bookmakers") or {}).values():
        for market, outcomes in (bm.get("markets") or {}).items():
            if market not in markets and not str(market).startswith("player_"):
                continue
            for o in outcomes:
                desc = o.get("description") or o.get("player")
                if desc:
                    players.add(str(desc))

    sims: dict[tuple[str, str], PropSimResult] = {}
    for name in players:
        usage = find_player(scripted, name) or find_player(profiles, name)
        if usage is None or usage.inactive:
            continue
        for market in markets:
            if not _market_fits(usage, market):
                continue
            try:
                sim = simulate_prop(usage, market, n_sims=n_sims)
                sims[(_norm(name), market)] = sim
                sims[(_norm(usage.player_name), market)] = sim
            except ValueError:
                continue
    return sims


def _market_fits(u: PlayerUsage, market: str) -> bool:
    if market.startswith("player_pass"):
        return u.position == "QB" or u.exp_pass_att > 10
    if market.startswith("player_rush"):
        return u.exp_rush_att > 2 or u.position == "RB"
    if "reception" in market or market == "player_anytime_td":
        return u.exp_targets > 1 or u.position in ("WR", "TE", "RB")
    return True


def _norm(name: str) -> str:
    return " ".join(str(name).strip().lower().replace(".", "").split())


def _main_line(lines: set[float]) -> float:
    if not lines:
        return 0.0
    # Mode-ish: median of offered lines as proxy for main
    arr = sorted(lines)
    return float(arr[len(arr) // 2])


def mock_prop_event(base_event: dict[str, Any]) -> dict[str, Any]:
    """Attach demo prop markets to a game event."""
    ev = dict(base_event)
    books = dict(ev.get("bookmakers") or {})
    props = {
        "player_pass_yds": [
            {"description": "Josh Allen", "name": "Over", "price": -115, "point": 259.5},
            {"description": "Josh Allen", "name": "Under", "price": -105, "point": 259.5},
            {"description": "Josh Allen", "name": "Over", "price": 240, "point": 300.5},
            {"description": "Josh Allen", "name": "Under", "price": -320, "point": 300.5},
            {"description": "Patrick Mahomes", "name": "Over", "price": -110, "point": 274.5},
            {"description": "Patrick Mahomes", "name": "Under", "price": -110, "point": 274.5},
        ],
        "player_reception_yds": [
            {"description": "Stefon Diggs", "name": "Over", "price": -110, "point": 74.5},
            {"description": "Stefon Diggs", "name": "Under", "price": -110, "point": 74.5},
            {"description": "Stefon Diggs", "name": "Over", "price": 250, "point": 99.5},
            {"description": "Stefon Diggs", "name": "Under", "price": -330, "point": 99.5},
            {"description": "Travis Kelce", "name": "Over", "price": -115, "point": 64.5},
            {"description": "Travis Kelce", "name": "Under", "price": -105, "point": 64.5},
        ],
        "player_receptions": [
            {"description": "Stefon Diggs", "name": "Over", "price": -120, "point": 5.5},
            {"description": "Stefon Diggs", "name": "Under", "price": 100, "point": 5.5},
            {"description": "Travis Kelce", "name": "Over", "price": -110, "point": 5.5},
            {"description": "Travis Kelce", "name": "Under", "price": -110, "point": 5.5},
        ],
        "player_rush_yds": [
            {"description": "James Cook", "name": "Over", "price": -110, "point": 68.5},
            {"description": "James Cook", "name": "Under", "price": -110, "point": 68.5},
        ],
    }
    for key, bm in list(books.items()):
        markets = dict(bm.get("markets") or {})
        markets.update(props)
        books[key] = {**bm, "markets": markets}
    # Ensure draftkings exists for retail shopping
    if "draftkings" not in books and books:
        first = next(iter(books.values()))
        books["draftkings"] = {
            "key": "draftkings",
            "title": "DraftKings",
            "is_sharp": False,
            "markets": props,
        }
    elif "draftkings" not in books:
        books["draftkings"] = {
            "key": "draftkings",
            "title": "DraftKings",
            "is_sharp": False,
            "markets": props,
        }
    ev["bookmakers"] = books
    return ev