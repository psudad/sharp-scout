"""NBA score-model replay schedule (travel/rest) and robust consensus lines."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.nba.score_model.engine import V2Engine, V2Params
from sharp_scout.nba.score_model.lines import robust_consensus_point, snapshot_game_lines
from sharp_scout.nba.score_model.state import _rest_days, rebuild_projection_history
from sharp_scout.nba.score_model.teams_geo import travel_miles


def test_rest_days_use_et_calendar_not_utc_midnight():
    # 7 PM ET Oct 27 → next night 10 PM ET Oct 28 is one ET rest day (b2b).
    last = {"BKN": datetime(2026, 10, 27, 23, 0, tzinfo=timezone.utc)}
    nxt = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)
    utc_gap = max((nxt.date() - last["BKN"].date()).days, 0)
    assert utc_gap == 2
    assert _rest_days("BKN", nxt, last) == 1


def test_replay_away_travel_uses_last_game_venue():
    engine = V2Engine(params=V2Params(), stage=3)
    t1 = datetime(2026, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 12, 0, 0, tzinfo=timezone.utc)
    games = [
        {
            "home": "BOS",
            "away": "LAL",
            "home_pts": 110,
            "away_pts": 105,
            "date": t1,
            "season": "2025-26",
            "game_poss": 100.0,
        },
        {
            "home": "NYK",
            "away": "LAL",
            "home_pts": 108,
            "away_pts": 102,
            "date": t2,
            "season": "2025-26",
            "game_poss": 100.0,
        },
    ]
    rebuild_projection_history(engine, games)
    row = engine.history[-1]
    expected = travel_miles("BOS", "NYK")
    assert expected > 150
    assert row.away == "LAL"
    assert row.away_travel == expected


def test_robust_consensus_total_anchors_pinnacle_and_drops_outliers():
    event = {
        "bookmakers": {
            "pinnacle": {
                "markets": {
                    "totals": [
                        {"side": "over", "point": 240.0, "price": -110},
                        {"side": "under", "point": 240.0, "price": -110},
                    ]
                }
            },
            "draftkings": {
                "markets": {
                    "totals": [
                        {"side": "over", "point": 240.5, "price": -110},
                        {"side": "under", "point": 240.5, "price": -110},
                    ]
                }
            },
            "outlier_book": {
                "markets": {
                    "totals": [
                        {"side": "over", "point": 248.5, "price": -110},
                        {"side": "under", "point": 248.5, "price": -110},
                    ]
                }
            },
        }
    }
    assert robust_consensus_point(event, "totals", side="over") == 240.25
    snap = snapshot_game_lines(event)
    assert snap["consensus_total"] == 240.25
    assert snap["pinnacle_total"] == 240.0


def test_robust_consensus_spread_without_sharp_uses_median_after_outlier_filter():
    event = {
        "bookmakers": {
            "draftkings": {
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -4.0, "price": -110},
                        {"side": "away", "point": 4.0, "price": -110},
                    ]
                }
            },
            "fanduel": {
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -4.5, "price": -110},
                        {"side": "away", "point": 4.5, "price": -110},
                    ]
                }
            },
            "outlier_book": {
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -10.0, "price": -110},
                        {"side": "away", "point": 10.0, "price": -110},
                    ]
                }
            },
        }
    }
    assert robust_consensus_point(event, "spreads", side="home") == -4.25
