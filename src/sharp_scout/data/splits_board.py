"""Action Network–style split board: tickets %, money %, and sharp-edge diff per market."""

from __future__ import annotations

from typing import Any, Literal

from sharp_scout.phase4.filters import _find_split_game

MarketKey = Literal["spread", "total", "moneyline"]
SidePair = tuple[str, str]


def money_ticket_diff(money_pct: float | None, ticket_pct: float | None) -> float | None:
    """Action Network Diff: handle % minus ticket % on the same side."""
    if money_pct is None or ticket_pct is None:
        return None
    return round(money_pct - ticket_pct, 4)


def _side_row(
    *,
    label: str,
    tickets: float | None,
    money: float | None,
) -> dict[str, Any]:
    diff = money_ticket_diff(money, tickets)
    return {
        "label": label,
        "tickets_pct": tickets,
        "money_pct": money,
        "diff_pct": diff,
    }


def _sharp_edge(sides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Side with the largest positive money-ticket diff (AN sharp-money signal)."""
    best_side = None
    best_diff = None
    for side, row in sides.items():
        d = row.get("diff_pct")
        if d is None:
            continue
        if best_diff is None or d > best_diff:
            best_diff = d
            best_side = side
    if best_side is None or best_diff is None or best_diff <= 0:
        return {
            "side": None,
            "team": None,
            "diff_pct": None,
            "available": False,
            "reason": "no positive money-ticket diff",
        }
    return {
        "side": best_side,
        "team": sides[best_side].get("label"),
        "diff_pct": best_diff,
        "available": True,
        "reason": f"+{best_diff:.0%} money vs tickets on {sides[best_side].get('label')}",
    }


def build_market_board(
    block: dict[str, Any],
    *,
    market: MarketKey,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    """One market row group (spread / total / moneyline) with AN-style diffs."""
    if market == "spread":
        sides = {
            "home": _side_row(
                label=home_team,
                tickets=block.get("home_bet_pct"),
                money=block.get("home_money_pct"),
            ),
            "away": _side_row(
                label=away_team,
                tickets=block.get("away_bet_pct"),
                money=block.get("away_money_pct"),
            ),
        }
        edge = _sharp_edge(sides)
        return {
            "market": "spread",
            "line": block.get("current_line"),
            "open_line": block.get("open_line"),
            "sides": sides,
            "sharp_edge": edge,
        }

    if market == "moneyline":
        sides = {
            "home": _side_row(
                label=home_team,
                tickets=block.get("home_bet_pct"),
                money=block.get("home_money_pct"),
            ),
            "away": _side_row(
                label=away_team,
                tickets=block.get("away_bet_pct"),
                money=block.get("away_money_pct"),
            ),
        }
        edge = _sharp_edge(sides)
        return {
            "market": "moneyline",
            "line": None,
            "open_line": None,
            "sides": sides,
            "sharp_edge": edge,
        }

    # total
    sides = {
        "over": _side_row(
            label="Over",
            tickets=block.get("over_bet_pct"),
            money=block.get("over_money_pct"),
        ),
        "under": _side_row(
            label="Under",
            tickets=block.get("under_bet_pct"),
            money=block.get("under_money_pct"),
        ),
    }
    edge = _sharp_edge(sides)
    return {
        "market": "total",
        "line": block.get("current_line"),
        "open_line": block.get("open_line"),
        "sides": sides,
        "sharp_edge": edge,
    }


def build_game_split_board(
    split_game: dict[str, Any] | None,
    *,
    home_team: str,
    away_team: str,
    event_id: str = "",
) -> dict[str, Any]:
    """Full per-game split board for dashboard / API."""
    if not split_game:
        return {
            "event_id": event_id,
            "home_team": home_team,
            "away_team": away_team,
            "available": False,
            "num_bets": None,
            "markets": {},
            "reason": "no Action Network row matched",
        }

    markets_raw = split_game.get("markets") or {}
    markets: dict[str, Any] = {}
    for mkey, an_key in (("spread", "spread"), ("total", "total"), ("moneyline", "moneyline")):
        block = markets_raw.get(an_key) or {}
        if any(
            block.get(k) is not None
            for k in (
                "home_bet_pct",
                "away_bet_pct",
                "over_bet_pct",
                "home_money_pct",
                "away_money_pct",
                "over_money_pct",
            )
        ):
            markets[mkey] = build_market_board(
                block, market=mkey, home_team=home_team, away_team=away_team
            )

    return {
        "event_id": event_id or split_game.get("game_id") or "",
        "home_team": home_team,
        "away_team": away_team,
        "available": bool(markets),
        "num_bets": split_game.get("raw_num_bets"),
        "source_book_id": (markets_raw.get("source_book_id") if isinstance(markets_raw, dict) else None),
        "markets": markets,
        "reason": None if markets else "Action Network row matched but no split %",
    }


def build_slate_split_boards(
    events: list[dict[str, Any]],
    splits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    boards = []
    for ev in events:
        home, away = ev["home_team"], ev["away_team"]
        split = _find_split_game(splits, home, away)
        boards.append(
            build_game_split_board(
                split,
                home_team=home,
                away_team=away,
                event_id=str(ev.get("event_id") or ""),
            )
        )
    return boards


def fetch_action_network_splits(*, date: str | None = None) -> list[dict[str, Any]]:
    """Fetch live Action Network splits; never silently substitutes mock data."""
    from sharp_scout.data.action_network import ActionNetworkClient
    from sharp_scout.data.line_memory import overlay_open_lines

    games = ActionNetworkClient().fetch_scoreboard(date=date)
    return overlay_open_lines(games)
