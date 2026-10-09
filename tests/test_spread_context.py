"""Plain-English spread labels and QA copy."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sharp_scout.copy.explain import describe_stage_pick
from sharp_scout.copy.spread_context import (
    format_model_margin,
    format_market_home_line,
    spread_line_gap_message,
    sync_play_sim_from_game,
)
from sharp_scout.qa.gate import review_play


def test_format_model_margin_sign_convention():
    assert "OSU by" in format_model_margin(0.4, "IOWA", "OSU")
    assert "IOWA by" in format_model_margin(-5.8, "IOWA", "OSU")


def test_format_market_home_line_underdog():
    assert format_market_home_line(14.0, "IOWA", "OSU") == "IOWA +14 (OSU by 14)"


def test_sync_play_overrides_stale_model_spread():
    play = {"model_spread": -5.8, "model_total": 40.0}
    game = {"model_spread": 0.38, "model_total": 56.3}
    sync_play_sim_from_game(play, game)
    assert play["model_spread"] == 0.38
    assert play["model_total"] == 56.3


def test_review_play_uses_fresh_game_spread_in_message():
    signals = {
        "demo": False,
        "n_games": 16,
        "n_splits_games": 10,
        "ratings": [{"team": f"T{i}", "power": i * 0.02, "off_epa": 0, "def_epa": 0} for i in range(32)]
        + [
            {"team": "IOWA", "power": 0.1, "off_epa": 0, "def_epa": 0},
            {"team": "OSU", "power": 0.12, "off_epa": 0, "def_epa": 0},
        ],
        "games": [
            {
                "event_id": "ev-osu",
                "home_team": "IOWA",
                "away_team": "OSU",
                "model_spread": 0.38,
                "commence_time": "2026-10-12T20:25:00+00:00",
            }
        ],
        "plays": [
            {
                "event_id": "ev-osu",
                "home_team": "IOWA",
                "away_team": "OSU",
                "market": "spreads",
                "side": "home",
                "line": 14.0,
                "filter_passed": True,
            }
        ],
        "signals": [
            {"event_id": "ev-osu", "market": "spreads", "side": "home", "line": 14.0, "book": "dk"},
            {"event_id": "ev-osu", "market": "spreads", "side": "home", "line": 14.0, "book": "fd"},
        ],
    }
    play = {
        "id": "osu-iowa",
        "event_id": "ev-osu",
        "home_team": "IOWA",
        "away_team": "OSU",
        "market": "spreads",
        "side": "home",
        "line": 14.0,
        "book": "rebet",
        "price": -110,
        "p_true": 0.58,
        "p_mkt": 0.49,
        "model_spread": -5.8,
        "edge": 0.12,
        "kickoff": "2026-10-12T20:25:00+00:00",
        "status": "pending",
    }
    review = review_play(play, signals, sport="ncaaf")
    assert play["model_spread"] == 0.38
    line_msgs = [
        i.message
        for i in review.issues
        if i.code == "spread_model_line_conflict"
    ]
    assert line_msgs
    assert "OSU by 0.4" in line_msgs[0]
    assert "IOWA +14" in line_msgs[0]


def test_describe_stage_pick_model_uses_s_mod_not_bet_line():
    pick = {
        "available": True,
        "team": "IOWA",
        "side": "home",
        "line": 13.5,
        "confidence": 0.78,
        "reason": "S_mod=+0.38 vs mkt +13.50 (home persp) → IOWA covers",
    }
    text = describe_stage_pick("model", pick, "IOWA", "OSU")
    assert "OSU by 0.4" in text
    assert "negative = home favored" not in text
