"""Prior decay + ridge gate (early season stays prior-heavy)."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.nba.score_model.engine import V2Engine, V2Params, TeamPrior


def test_effective_rating_prior_heavy_early_season():
    engine = V2Engine(params=V2Params(prior_decay_games=18.0), stage=3)
    engine.season_priors["OKC"] = TeamPrior(off=120.0, def_=108.0, pace=100.0)
    engine.team_off["OKC"] = 90.0
    engine.team_games["OKC"] = 3
    eff = engine._effective_rating("OKC", "off")
    w = 3 / 18
    expected = w * 90.0 + (1 - w) * 120.0
    assert abs(eff - expected) < 0.01


def test_ridge_not_used_until_min_team_games():
    engine = V2Engine(params=V2Params(ridge_min_team_games=10), stage=3)
    engine.season_priors["OKC"] = TeamPrior(off=115.0, def_=110.0, pace=100.0)
    engine.season_priors["LAC"] = TeamPrior(off=112.0, def_=112.0, pace=100.0)
    engine.team_off.update({"OKC": 115.0, "LAC": 112.0})
    engine.team_def.update({"OKC": 110.0, "LAC": 112.0})
    engine.team_pace.update({"OKC": 100.0, "LAC": 100.0})
    engine.team_games.update({"OKC": 3, "LAC": 3})
    engine._cached_off = {"OKC": 5.0, "LAC": 2.0}
    engine._cached_def = {"OKC": -2.0, "LAC": 1.0}
    engine._ridge_intercept = 112.0
    p = engine.project("OKC", "LAC", game_date=datetime.now(timezone.utc))
    assert 200 < p["total"] < 250
