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


def test_slate_dates_et_covers_every_kickoff_date():
    """A college week spans Thu–Sat; all three dates must be requested from AN."""
    from sharp_scout.data.action_network import slate_dates_et

    events = [
        {"commence_time": "2026-09-03T23:00:00+00:00"},  # Thu 7pm ET
        {"commence_time": "2026-09-04T01:00:00+00:00"},  # Thu 9pm ET
        {"commence_time": "2026-09-05T16:00:00+00:00"},  # Sat noon ET
    ]
    assert slate_dates_et(events) == ["20260903", "20260905"]


def test_fetch_scoreboard_dates_merges_and_prefers_richer_row():
    from sharp_scout.data.action_network import ActionNetworkClient

    thin = {"game_id": 1, "home_team": "WAKE", "away_team": "AKR", "markets": {"spread": {}}}
    rich = {
        "game_id": 1,
        "home_team": "WAKE",
        "away_team": "AKR",
        "markets": {"spread": {"home_bet_pct": 0.7, "home_money_pct": 0.5}},
    }
    other = {"game_id": 2, "home_team": "GT", "away_team": "COLO", "markets": {"spread": {}}}

    client = ActionNetworkClient(league="ncaaf")
    calls: list[str] = []

    def fake(date=None):
        calls.append(date)
        return {"20260903": [thin], "20260905": [rich, other]}[date]

    client.fetch_scoreboard = fake  # type: ignore[method-assign]
    merged = client.fetch_scoreboard_dates(["20260903", "20260905", "20260903"])

    assert calls == ["20260903", "20260905"]  # deduped
    assert len(merged) == 2
    by_id = {r["game_id"]: r for r in merged}
    assert by_id[1]["markets"]["spread"]["home_bet_pct"] == 0.7  # richer row won
