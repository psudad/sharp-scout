"""Split board (Action Network Diff) tests."""

from __future__ import annotations

from sharp_scout.data.action_network import mock_splits
from sharp_scout.data.splits_board import (
    build_game_split_board,
    build_market_board,
    money_ticket_diff,
)


def test_money_ticket_diff():
    assert money_ticket_diff(0.54, 0.51) == 0.03
    assert money_ticket_diff(0.29, 0.16) == 0.13
    assert money_ticket_diff(None, 0.5) is None


def test_sharp_edge_picks_positive_diff_side():
  # Falcons ML: 16% tickets, 29% money → +13% diff on home
    block = {
        "home_bet_pct": 0.16,
        "away_bet_pct": 0.84,
        "home_money_pct": 0.29,
        "away_money_pct": 0.71,
    }
    board = build_market_board(block, market="moneyline", home_team="ATL", away_team="DEN")
    edge = board["sharp_edge"]
    assert edge["available"] is True
    assert edge["side"] == "home"
    assert edge["team"] == "ATL"
    assert edge["diff_pct"] == 0.13


def test_build_game_split_board_from_mock():
    split = mock_splits()[0]
    board = build_game_split_board(split, home_team="BUF", away_team="KC", event_id="x")
    assert board["available"] is True
    assert "spread" in board["markets"]
    sp = board["markets"]["spread"]
    assert sp["sides"]["home"]["tickets_pct"] == 0.72
    assert sp["sides"]["away"]["money_pct"] == 0.59
