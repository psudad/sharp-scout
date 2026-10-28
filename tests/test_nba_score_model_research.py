"""Offline tests for NBA score projection research module."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sharp_scout.research.nba_score_model.data_loader import (
    enrich_yahoo_with_espn_scores,
    load_sbr_games,
    scores_match_yahoo_line,
)
from sharp_scout.research.nba_score_model.evaluate import summarize, tune_blend, walk_forward
from sharp_scout.research.nba_score_model.ratings import ModelParams, RatingEngine, p_cover_home, p_over


def _sample_games(n: int = 40) -> list[dict]:
    base = datetime(2023, 1, 1, tzinfo=timezone.utc)
    teams = [("BOS", "NYK"), ("LAL", "GSW"), ("MIA", "CHI"), ("DAL", "PHX")]
    out = []
    for i in range(n):
        away, home = teams[i % len(teams)]
        dt = base.replace(day=1 + (i % 28))
        hs, as_ = 110 + (i % 7), 108 + (i % 5)
        spread = -2.5 if i % 2 == 0 else 3.0
        total = 225.5
        out.append(
            {
                "date": dt,
                "season": "2022-23",
                "away": away,
                "home": home,
                "away_pts": as_,
                "home_pts": hs,
                "close_spread_home": spread,
                "close_total": total,
                "source": "test",
            }
        )
    return out


def test_rating_engine_project_and_observe():
    eng = RatingEngine(params=ModelParams())
    g = _sample_games(1)[0]
    eng.observe(g)
    proj = eng.project(g["home"], g["away"], game_date=g["date"])
    assert proj["total"] > 180
    assert proj["margin"] == proj["home_pts"] - proj["away_pts"]


def test_p_cover_monotonic():
    assert p_cover_home(5.0, -3.0, 10.0) > p_cover_home(0.0, -3.0, 10.0)
    assert p_over(230.0, 220.0, 12.0) > p_over(215.0, 220.0, 12.0)


def test_walk_forward_and_summarize():
    games = _sample_games(60)
    params = ModelParams(recency_half_life_days=30.0)
    ev = walk_forward(games, params)
    assert len(ev.preds) == 60
    blend = tune_blend(ev.preds)
    summary = summarize(ev.preds, blend)
    assert summary["n_oos_games"] == 60
    assert "margin_mae" in summary


def test_enrich_yahoo_scores_validated():
    g = {
        "date": datetime(2023, 3, 15, tzinfo=timezone.utc),
        "away": "BOS",
        "home": "NYK",
        "home_pts": None,
        "away_pts": None,
        "close_spread_home": -3.5,
        "close_total": 220.5,
        "spread_home_won": True,
        "total_over_won": True,
    }
    # BOS wins by 6 at NYK -> home margin -6, home spread -3.5 -> away covers (spread_home_won False)
    idx = {"2023-03-15|BOS@NYK": {"home": 99, "away": 105}}
    enrich_yahoo_with_espn_scores([g], idx)
    assert g["home_pts"] is None  # rejected: spread grade disagrees

    g2 = {
        "date": datetime(2023, 3, 15, tzinfo=timezone.utc),
        "away": "BOS",
        "home": "NYK",
        "home_pts": None,
        "away_pts": None,
        "close_spread_home": -3.5,
        "close_total": 220.5,
        "spread_home_won": False,
        "total_over_won": False,
    }
    enrich_yahoo_with_espn_scores([g2], idx)
    assert g2["home_pts"] == 99


def test_scores_match_yahoo_line():
    g = {
        "home_pts": 110,
        "away_pts": 100,
        "close_spread_home": -4.5,
        "close_total": 215.5,
        "spread_home_won": True,
        "total_over_won": False,
    }
    assert scores_match_yahoo_line(g)


def test_enrich_ignores_undated_fallback():
    g = {
        "date": datetime(2023, 3, 15, tzinfo=timezone.utc),
        "away": "BOS",
        "home": "NYK",
        "home_pts": None,
        "away_pts": None,
        "close_spread_home": -3.5,
        "close_total": 220.5,
        "spread_home_won": True,
        "total_over_won": True,
    }
    idx = {"BOS@NYK": {"home": 120, "away": 100}}  # undated only — must not attach
    enrich_yahoo_with_espn_scores([g], idx)
    assert g["home_pts"] is None


def test_load_sbr_skips_missing_file(tmp_path: Path):
    assert load_sbr_games(tmp_path / "missing.json") == []
