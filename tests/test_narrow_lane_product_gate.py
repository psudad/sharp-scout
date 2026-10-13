"""Narrow LOCKED lanes — Phase-4 confirmed + Pinnacle ≥50%."""

from __future__ import annotations

import pytest

from sharp_scout.config import get_settings
from sharp_scout.qa.product_gate import (
    apply_board_flags,
    evaluate_product_play,
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
    play = _sig(sport="ncaaf")
    r = evaluate_product_play(play, signals=None, sport="ncaaf")
    assert r.ok, r.note()


def test_lane_fails_without_pinnacle_reference(narrow_lanes_on):
    play = _sig(sharp_book="circa", p_fair=0.55, p_mkt=0.55)
    apply_board_flags(play, sport="ncaaf")
    r = evaluate_product_play(play, signals=None, sport="ncaaf")
    assert not r.ok and "Pinnacle" in r.note()
    assert play.get("board_flags") == ["no_pinnacle"]


def test_lane_fails_pinnacle_below_fifty(narrow_lanes_on):
    play = _sig(p_fair=0.48, p_mkt=0.48)
    r = evaluate_product_play(play, signals=None, sport="ncaaf")
    assert not r.ok
    assert "0.48" in r.note() or "50%" in r.note()


def test_lane_skips_spread_money_guardrail(narrow_lanes_on):
    """NFL spread lane replaces product spread handle guardrail."""
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


def test_filter_not_passed_never_certifies(narrow_lanes_on):
    play = _sig(filter_passed=False)
    out = select_certified_plays([play], signals={"signals": [play]}, sport="ncaaf")
    assert out == []


def test_priority_ncaaf_totals_before_ncaaf_spread(narrow_lanes_on):
    ncaaf_tot = _sig(event_id="t1", edge=0.05, market="totals")
    ncaaf_sp = _sig(
        event_id="s1",
        edge=0.09,
        market="spreads",
        side="home",
        line=-3.5,
    )
    cands = [ncaaf_sp, ncaaf_tot]
    out = select_certified_plays(cands, signals={"signals": cands}, sport="ncaaf")
    assert out[0]["market"] == "totals"
    assert narrow_lane_rank(ncaaf_tot, "ncaaf") == 0
    assert narrow_lane_rank(ncaaf_sp, "ncaaf") == 2


def test_lane_priority_order_config(narrow_lanes_on):
    nfl_sp = _sig(
        event_id="n1",
        market="spreads",
        side="away",
        line=3.5,
        home_team="BUF",
        away_team="KC",
    )
    assert narrow_lane_rank(nfl_sp, "nfl") == 1


def test_nfl_spreads_lane_selects_on_nfl_run(narrow_lanes_on):
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
    assert len(out) == 1 and out[0]["market"] == "spreads"


def test_outside_lane_not_certified_when_narrow_enabled(narrow_lanes_on):
    play = _sig(market="totals", edge=0.06, home_team="BUF", away_team="KC")
    r = evaluate_product_play(play, signals=None, sport="nfl")
    assert not r.ok and "outside narrow" in r.note()
