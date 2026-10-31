"""NCAAF spread lane removal — shadow append + grandfather QA for official rows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sharp_scout.config import get_settings
from sharp_scout.ledger.tracker import append_signals, load_ledger
from sharp_scout.qa.gate import review_play
from sharp_scout.qa.product_gate import (
    evaluate_product_play,
    is_grandfathered_ncaaf_spread_official,
    select_certified_plays,
    select_research_shadow_plays,
)


def _ncaaf_spread(**kw):
    kick = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    base = {
        "filter_passed": True,
        "sport": "ncaaf",
        "event_id": "ev-wmu-bgsu",
        "home_team": "WESTERN MICHIGAN",
        "away_team": "BOWLING GREEN",
        "market": "spreads",
        "side": "home",
        "line": -13.0,
        "book": "ballybet",
        "price": -110,
        "tier": "play",
        "edge": 0.048,
        "p_fair": 0.53,
        "p_mkt": 0.53,
        "sharp_book": "pinnacle",
        "sharp_price": -109,
        "kickoff": kick,
        "commence_time": kick,
        "flags": {"money_split": True, "rlm": True},
    }
    base.update(kw)
    return base


@pytest.fixture
def narrow_lanes_on(monkeypatch):
    monkeypatch.setenv("PRODUCT_NARROW_LANES_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ncaaf_spread_not_certified(narrow_lanes_on):
    play = _ncaaf_spread()
    assert not evaluate_product_play(play, sport="ncaaf").ok
    assert select_certified_plays([play], signals={"signals": [play]}, sport="ncaaf") == []


def test_ncaaf_spread_research_shadow_not_official_append(narrow_lanes_on, tmp_path):
    play = _ncaaf_spread(tier="play")
    shadow = select_research_shadow_plays(
        [play], signals={"signals": [play]}, sport="ncaaf"
    )
    assert len(shadow) == 1
    path = tmp_path / "ncaaf_ledger.json"
    append_signals(shadow, path=path, only_validated=False, status="watchlist")
    row = load_ledger(path)["plays"][0]
    assert row["status"] == "watchlist"
    assert row["market"] == "spreads"


def test_ncaaf_total_still_certifies(narrow_lanes_on):
    play = _ncaaf_spread(market="totals", side="under", line=49.5, edge=0.06)
    out = select_certified_plays([play], signals={"signals": [play]}, sport="ncaaf")
    assert len(out) == 1 and out[0]["market"] == "totals"


def test_nfl_spread_still_certifies(narrow_lanes_on):
    play = _ncaaf_spread(
        sport="nfl",
        event_id="ev-kc-buf",
        home_team="BUF",
        away_team="KC",
        line=3.5,
        side="away",
        edge=0.05,
    )
    out = select_certified_plays([play], signals={"signals": [play]}, sport="nfl")
    assert len(out) == 1


def test_grandfather_official_ncaaf_spread_skips_product_gate_qa(narrow_lanes_on):
    from sharp_scout.qa.gate import _logical_play_key

    play = _ncaaf_spread(p_true=0.53)
    assert is_grandfathered_ncaaf_spread_official(play, sport="ncaaf")
    assert not evaluate_product_play(play, sport="ncaaf").ok
    signals = {
        "plays": [play],
        "games": [
            {
                "event_id": play["event_id"],
                "home_team": play["home_team"],
                "away_team": play["away_team"],
                "commence_time": play["kickoff"],
            }
        ],
        "ratings": [
            {"team": play["home_team"], "power": 0.05},
            {"team": play["away_team"], "power": -0.05},
        ],
        "events": [
            {
                "event_id": play["event_id"],
                "bookmakers": {
                    "draftkings": {
                        "markets": {
                            "spreads": {
                                "outcomes": [
                                    {"name": play["home_team"], "point": -13.0, "price": -110},
                                    {"name": play["away_team"], "point": 13.0, "price": -110},
                                ]
                            }
                        }
                    },
                    "fanduel": {
                        "markets": {
                            "spreads": {
                                "outcomes": [
                                    {"name": play["home_team"], "point": -13.0, "price": -108},
                                    {"name": play["away_team"], "point": 13.0, "price": -112},
                                ]
                            }
                        }
                    },
                },
            }
        ],
    }
    review = review_play(
        {**play, "id": "a5f2fefa", "status": "pending"},
        signals,
        sport="ncaaf",
        validated_keys={_logical_play_key(play)},
    )
    pg = [i for i in review.issues if i.code == "product_gate"]
    assert not pg, pg


def test_watchlist_ncaaf_spread_not_grandfathered(narrow_lanes_on):
    play = _ncaaf_spread(tier="watch", status="watchlist")
    assert not is_grandfathered_ncaaf_spread_official(play, sport="ncaaf")
