"""Narrow LOCKED lanes — Phase-4 confirmed + Pinnacle ≥50%."""

from __future__ import annotations

import pytest

from sharp_scout.config import get_settings
from sharp_scout.qa.product_gate import (
    apply_high_confidence_flag,
    evaluate_product_play,
    has_high_confidence_booster,
    narrow_lane_rank,
    select_certified_plays,
)


def _sig(**kw):
    base = {
        "filter_passed": True,
        "event_id": "e1",
        "home_team": "ALA",
        "away_team": "UGA",
        "market": "totals",
        "side": "over",
        "line": 52.5,
        "book": "draftkings",
        "tier": "play",
        "edge": 0.06,
        "p_fair": 0.52,
        "p_mkt": 0.52,
        "sharp_book": "pinnacle",
        "price": -110,
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


def test_lane_passes_confirmed_with_pinnacle(narrow_lanes_on):
    r = evaluate_product_play(_sig(), signals=None, sport="ncaaf")
    assert r.ok, r.note()


def test_ncaaf_totals_uses_four_percent_floor_not_whitelist(narrow_lanes_on):
    r = evaluate_product_play(_sig(edge=0.03), signals=None, sport="ncaaf")
    assert not r.ok and "4%" in r.note()


def test_ncaaf_total_at_three_point_five_percent_rejected(narrow_lanes_on):
    r = evaluate_product_play(_sig(edge=0.035), signals=None, sport="ncaaf")
    assert not r.ok and "4%" in r.note()


def test_nfl_spread_at_three_point_four_percent_certifies(narrow_lanes_on):
    play = _sig(
        market="spreads",
        side="away",
        line=8.0,
        home_team="KC",
        away_team="LAC",
        edge=0.034,
        p_fair=0.50,
    )
    r = evaluate_product_play(play, signals=None, sport="nfl")
    assert r.ok, r.note()


def test_nfl_spread_at_two_point_nine_percent_rejected(narrow_lanes_on):
    play = _sig(
        market="spreads",
        side="away",
        line=8.0,
        home_team="KC",
        away_team="LAC",
        edge=0.029,
        p_fair=0.50,
    )
    r = evaluate_product_play(play, signals=None, sport="nfl")
    assert not r.ok and "3%" in r.note()


def test_nfl_spread_at_twelve_percent_rejected(narrow_lanes_on):
    play = _sig(
        market="spreads",
        side="away",
        line=8.0,
        home_team="KC",
        away_team="LAC",
        edge=0.12,
        p_fair=0.55,
    )
    r = evaluate_product_play(play, signals=None, sport="nfl")
    assert not r.ok and "ceiling" in r.note()


def test_ev_ceiling_applies_to_ncaaf_totals_lane(narrow_lanes_on):
    r = evaluate_product_play(_sig(edge=0.15), signals=None, sport="ncaaf")
    assert not r.ok and "ceiling" in r.note()


def test_ncaaf_spreads_lane_certifies_with_four_to_twelve_ev(narrow_lanes_on):
    play = _sig(market="spreads", side="home", line=-3.5, edge=0.07, p_fair=0.51)
    r = evaluate_product_play(play, signals=None, sport="ncaaf")
    assert r.ok, r.note()
    out = select_certified_plays([play], signals={"signals": [play]}, sport="ncaaf")
    assert len(out) == 1
    assert out[0]["market"] == "spreads"


def test_ncaaf_spread_below_four_percent_rejected(narrow_lanes_on):
    play = _sig(market="spreads", side="home", line=-3.5, edge=0.035, p_fair=0.51)
    r = evaluate_product_play(play, signals=None, sport="ncaaf")
    assert not r.ok and "4%" in r.note()


def test_ncaaf_spread_at_twelve_percent_rejected(narrow_lanes_on):
    play = _sig(market="spreads", side="home", line=-3.5, edge=0.12, p_fair=0.55)
    r = evaluate_product_play(play, signals=None, sport="ncaaf")
    assert not r.ok and "ceiling" in r.note()


def test_lane_skips_spread_money_guardrail(narrow_lanes_on):
    play = _sig(
        market="spreads",
        side="away",
        line=7.5,
        home_team="BUF",
        away_team="KC",
        edge=0.08,
        p_fair=0.53,
    )
    signals = {"signals": [play, _sig(book="fanduel")], "split_boards": []}
    r = evaluate_product_play(play, signals=signals, sport="nfl")
    assert r.ok, r.note()


def test_high_confidence_booster_never_certifies_alone(narrow_lanes_on):
    play = _sig(
        filter_passed=False,
        flags={"money_split": True, "rlm": True},
    )
    assert has_high_confidence_booster(play)
    out = select_certified_plays([play], signals={"signals": [play]}, sport="ncaaf")
    assert out == []


def test_high_confidence_ranks_before_higher_edge_without_booster(narrow_lanes_on):
    low_edge_boost = _sig(
        event_id="a",
        edge=0.05,
        flags={"money_split": True, "rlm": True},
    )
    high_edge = _sig(event_id="b", edge=0.10, flags={"money_split": False, "rlm": False})
    out = select_certified_plays(
        [high_edge, low_edge_boost],
        signals={"signals": [high_edge, low_edge_boost]},
        sport="ncaaf",
    )
    assert len(out) == 2
    assert out[0]["event_id"] == "a"
    assert out[0].get("high_confidence") is True


def test_nfl_spreads_lane_on_nfl_run(narrow_lanes_on):
    play = _sig(
        event_id="n2",
        market="spreads",
        side="away",
        line=3.5,
        home_team="BUF",
        away_team="KC",
        edge=0.07,
    )
    out = select_certified_plays([play], signals={"signals": [play]}, sport="nfl")
    assert len(out) == 1


def test_lane_priority_ncaaf_totals_before_spreads(narrow_lanes_on):
    assert narrow_lane_rank(_sig(market="totals"), "ncaaf") == 0
    assert narrow_lane_rank(_sig(market="spreads", side="home", line=-3.5), "ncaaf") == 1
    nfl_sp = _sig(
        market="spreads",
        side="away",
        line=3.5,
        home_team="BUF",
        away_team="KC",
    )
    assert narrow_lane_rank(nfl_sp, "nfl") == 2


def test_apply_high_confidence_flag_only_when_both_signals(narrow_lanes_on):
    p = _sig(flags={"money_split": True, "rlm": False})
    apply_high_confidence_flag(p)
    assert "high_confidence" not in p
    p2 = _sig(flags={"money_split": True, "rlm": True})
    apply_high_confidence_flag(p2)
    assert p2.get("high_confidence") is True
