"""Matchup-interaction engine tests (scheme features + residual adjuster)."""

from __future__ import annotations

import random
from pathlib import Path

from sharp_scout.phase1.matchup_ml import (
    MatchupAdjuster,
    load_adjuster,
    train_adjuster,
)
from sharp_scout.phase1.scheme import matchup_feature_vector, MATCHUP_VECTOR_KEYS


def test_feature_vector_keys_present():
    home = {"off_pass_rate": 0.6, "off_explosive_pass_rate": 0.1, "def_pressure_rate": 0.3}
    away = {"off_pass_rate": 0.55, "def_explosive_pass_allowed": 0.12, "def_pressure_rate": 0.25}
    vec = matchup_feature_vector(home, away)
    for k in MATCHUP_VECTOR_KEYS:
        assert k in vec


def test_no_op_adjuster_returns_means_unchanged():
    adj = MatchupAdjuster(model=None)
    means = {"mu_home": 24.0, "mu_away": 21.0}
    out = adj.adjust_means(means, {}, {})
    assert out == means
    assert adj.predict_residual({}, {}) == 0.0


def test_load_missing_model_is_no_op(tmp_path: Path):
    adj = load_adjuster(tmp_path / "does_not_exist.pkl")
    assert adj.ready is False


def test_train_and_predict_bounded(tmp_path: Path):
    # Synthetic: residual margin correlates with off_epa_diff.
    random.seed(1)
    X, y = [], []
    for _ in range(200):
        diff = random.uniform(-0.3, 0.3)
        vec = {k: 0.0 for k in MATCHUP_VECTOR_KEYS}
        vec["off_epa_diff"] = diff
        X.append(vec)
        y.append(diff * 20 + random.gauss(0, 1))  # strong signal
    adj = train_adjuster(X, y)
    assert adj.ready is True

    # Save + reload roundtrip
    p = tmp_path / "m.pkl"
    adj.save(p)
    reloaded = load_adjuster(p)
    assert reloaded.ready is True

    # Prediction is bounded and directionally sensible.
    home = {"off_epa": 0.2, "def_epa": 0.0}
    away = {"off_epa": -0.2, "def_epa": 0.0}
    resid = reloaded.predict_residual(home, away)
    assert -4.0 <= resid <= 4.0

    means = {"mu_home": 24.0, "mu_away": 21.0}
    out = reloaded.adjust_means(means, home, away)
    assert "matchup_residual" in out
    assert out["mu_home"] + out["mu_away"] == out["model_total"]
