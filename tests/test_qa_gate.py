"""Tests for QA gate — data provenance and play sanity checks."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sharp_scout.qa.gate import (
    QAIssue,
    apply_qa_gate,
    review_play,
    review_signals,
)


def _base_signals(**overrides) -> dict:
    ratings = [
        {"team": "LV", "power": 0.05, "off_epa": 0, "def_epa": 0},
        {"team": "MIA", "power": 0.03, "off_epa": 0, "def_epa": 0},
    ]
    ratings += [
        {"team": f"T{i}", "power": i * 0.01, "off_epa": 0, "def_epa": 0} for i in range(30)
    ]
    payload = {
        "demo": False,
        "n_games": 16,
        "n_splits_games": 10,
        "ratings": ratings,
        "games": [
            {
                "event_id": "ev1",
                "home_team": "LV",
                "away_team": "MIA",
                "p_home_win": 0.527,
                "commence_time": "2026-09-13T20:25:00+00:00",
            }
        ],
        "plays": [],
        "signals": [],
        "split_boards": [
            {
                "home_team": "LV",
                "away_team": "MIA",
                "markets": {
                    "spread": {
                        "sharp_edge": {
                            "available": True,
                            "side": "home",
                            "team": "LV",
                            "diff_pct": 0.21,
                        }
                    },
                    "moneyline": {
                        "sharp_edge": {
                            "available": True,
                            "side": "away",
                            "team": "MIA",
                            "diff_pct": 0.17,
                        }
                    },
                },
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_demo_mode_blocks_deploy():
    issues = review_signals(_base_signals(demo=True))
    assert any(i.code == "demo_mode" and i.severity == "block" for i in issues)


def test_flat_ratings_block_deploy():
    flat = [{"team": f"T{i}", "power": 0.0, "off_epa": 0, "def_epa": 0} for i in range(32)]
    issues = review_signals(_base_signals(ratings=flat))
    assert any(i.code == "flat_ratings_spread" for i in issues)


def test_mia_ml_quarantined_for_model_conflict():
    signals = _base_signals()
    play = {
        "id": "abc",
        "event_id": "ev1",
        "home_team": "LV",
        "away_team": "MIA",
        "market": "h2h",
        "side": "away",
        "line": None,
        "book": "betfair_ex_eu",
        "price": 180.0,
        "p_true": 0.4482,
        "edge": 0.255,
        "kickoff": "2026-09-13T20:25:00+00:00",
        "status": "pending",
    }
    review = review_play(play, signals, sport="nfl", validated_keys=set())
    codes = {i.code for i in review.issues}
    assert review.action in ("quarantine", "void")
    assert "ml_model_conflict" in codes
    assert "cross_market_conflict" in codes
    assert "not_revalidated" in codes


def test_spread_model_conflict_quarantined():
    signals = _base_signals(
        plays=[
            {
                "event_id": "ev1",
                "home_team": "LV",
                "away_team": "MIA",
                "market": "spreads",
                "side": "home",
                "line": 3.0,
                "filter_passed": True,
            }
        ],
        games=[
            {
                "event_id": "ev1",
                "home_team": "LV",
                "away_team": "MIA",
                "p_home_win": 0.65,
                "model_spread": -4.5,
                "commence_time": "2026-09-13T20:25:00+00:00",
            }
        ],
        signals=[
            {"event_id": "ev1", "market": "spreads", "side": "home", "line": 3.0, "book": "draftkings"},
            {"event_id": "ev1", "market": "spreads", "side": "home", "line": 3.0, "book": "fanduel"},
        ],
    )
    play = {
        "id": "fsu-style",
        "event_id": "ev1",
        "home_team": "LV",
        "away_team": "MIA",
        "market": "spreads",
        "side": "home",
        "line": 3.0,
        "book": "rebet",
        "price": -125,
        "p_true": 0.758,
        "p_mkt": 0.486,
        "model_spread": -4.48,
        "edge": 0.364,
        "kickoff": "2026-09-13T20:25:00+00:00",
        "status": "pending",
    }
    review = review_play(play, signals, sport="nfl")
    codes = {i.code for i in review.issues}
    assert review.action == "quarantine"
    assert "spread_model_conflict" in codes


def test_corroborated_spread_passes():
    signals = _base_signals(
        plays=[
            {
                "event_id": "ev1",
                "home_team": "LV",
                "away_team": "MIA",
                "market": "spreads",
                "side": "home",
                "line": -3.5,
                "filter_passed": True,
            }
        ],
        signals=[
            {"event_id": "ev1", "market": "spreads", "side": "home", "line": -3.5, "book": "draftkings"},
            {"event_id": "ev1", "market": "spreads", "side": "home", "line": -3.5, "book": "fanduel"},
        ],
    )
    play = {
        "id": "spread1",
        "event_id": "ev1",
        "home_team": "LV",
        "away_team": "MIA",
        "market": "spreads",
        "side": "home",
        "line": -3.5,
        "book": "draftkings",
        "price": -110,
        "p_true": 0.58,
        "edge": 0.05,
        "kickoff": "2026-09-13T20:25:00+00:00",
        "status": "pending",
    }
    review = review_play(play, signals, sport="nfl")
    assert review.action == "approve"


def test_stale_kickoff_voided(tmp_path):
    signals = _base_signals()
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        """{
  "plays": [{
    "id": "stale",
    "event_id": "old",
    "home_team": "DAL",
    "away_team": "NYG",
    "market": "spreads",
    "side": "away",
    "line": 4.5,
    "book": "draftkings",
    "price": -110,
    "p_true": 0.66,
    "edge": 0.26,
    "kickoff": "2027-01-03T18:00:00+00:00",
    "status": "pending"
  }],
  "stage_cards": []
}"""
    )
    result = apply_qa_gate("nfl", signals=signals, apply=True, ledger_path=ledger_path)
    assert result.voided >= 1
    import json

    ledger = json.loads(ledger_path.read_text())
    assert ledger["plays"][0]["status"] == "void"
