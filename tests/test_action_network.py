"""Action Network parser + diagnose tests (live public endpoint when available)."""

from __future__ import annotations

from sharp_scout.data.action_network import ActionNetworkClient, _bet_info_pcts, _pct


def test_pct_helpers():
    assert _pct(55) == 0.55
    assert _pct(0.55) == 0.55
    assert _pct(None) is None
    t, m = _bet_info_pcts({"tickets": {"percent": 72}, "money": {"percent": 41}})
    assert t == 0.72 and m == 0.41


def test_normalize_markets_from_fixture():
    client = ActionNetworkClient(cookie="")
    raw = {
        "id": 1,
        "home_team_id": 10,
        "away_team_id": 20,
        "num_bets": 1000,
        "status": "scheduled",
        "teams": [
            {"id": 20, "abbr": "KC"},
            {"id": 10, "abbr": "BUF"},
        ],
        "markets": {
            "15": {
                "event": {
                    "spread": [
                        {
                            "side": "home",
                            "value": 2.5,
                            "team_id": 10,
                            "bet_info": {
                                "tickets": {"percent": 72},
                                "money": {"percent": 41},
                            },
                        },
                        {
                            "side": "away",
                            "value": -2.5,
                            "team_id": 20,
                            "bet_info": {
                                "tickets": {"percent": 28},
                                "money": {"percent": 59},
                            },
                        },
                    ],
                    "total": [
                        {
                            "side": "over",
                            "value": 47.5,
                            "bet_info": {
                                "tickets": {"percent": 61},
                                "money": {"percent": 55},
                            },
                        },
                        {
                            "side": "under",
                            "value": 47.5,
                            "bet_info": {
                                "tickets": {"percent": 39},
                                "money": {"percent": 45},
                            },
                        },
                    ],
                    "moneyline": [],
                }
            }
        },
    }
    g = client._normalize_game(raw)
    assert g["home_team"] == "BUF"
    assert g["away_team"] == "KC"
    assert g["markets"]["spread"]["home_bet_pct"] == 0.72
    assert g["markets"]["spread"]["away_money_pct"] == 0.59
    assert g["markets"]["spread"]["current_line"] == 2.5
    assert g["markets"]["total"]["over_bet_pct"] == 0.61


def test_live_scoreboard_or_skip():
    """Live call — skip assertion hard-fail if AN is down / offseason empty."""
    client = ActionNetworkClient(cookie="")
    report = client.diagnose()
    assert "n_games" in report
    assert "pro_splits_ready" in report
    # When games exist, we expect ticket+money after parser fix
    if report["n_games"] > 0:
        assert report["games_with_money_pct"] >= 1 or report["games_with_ticket_pct"] >= 1
