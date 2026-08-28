"""Matchup-interaction ML engine — a residual layer on top of the ridge/EPA baseline.

Per Tom's guardrail, this **does not replace** the additive `matchup_means()` model. It
learns the *interaction residual*: given scheme/matchup features, how much does the real
home margin differ from what a purely additive model would predict? At inference it returns
a **bounded points adjustment** applied to the simulation means.

Model: gradient boosting via scikit-learn's ``HistGradientBoostingRegressor`` (ships with
sklearn — no new runtime dependency). If LightGBM is installed it is used instead. With the
small NFL sample (~272 games/season) we keep the model shallow and clamp the output.

Everything degrades gracefully: no trained model → zero adjustment → identical to today.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from sharp_scout.config import DATA_DIR
from sharp_scout.phase1.scheme import MATCHUP_VECTOR_KEYS, matchup_feature_vector

logger = logging.getLogger(__name__)

MODEL_PATH = DATA_DIR / "matchup_model.pkl"

# Interaction correction is a refinement, not a takeover — clamp it hard.
MAX_ADJUSTMENT_POINTS = 4.0
MIN_TRAIN_ROWS = 100


class MatchupAdjuster:
    """Wraps a fitted regressor that predicts the interaction residual (home-margin points)."""

    def __init__(self, model: Any = None, feature_keys: tuple[str, ...] = MATCHUP_VECTOR_KEYS):
        self.model = model
        self.feature_keys = tuple(feature_keys)

    @property
    def ready(self) -> bool:
        return self.model is not None

    def _vectorize(self, vec: dict[str, float]) -> np.ndarray:
        return np.array([[float(vec.get(k, 0.0)) for k in self.feature_keys]], dtype=float)

    def predict_residual(self, home_feats: dict[str, float], away_feats: dict[str, float]) -> float:
        if not self.ready:
            return 0.0
        vec = matchup_feature_vector(home_feats, away_feats)
        try:
            pred = float(self.model.predict(self._vectorize(vec))[0])
        except Exception as exc:  # noqa: BLE001
            logger.debug("matchup predict failed: %s", exc)
            return 0.0
        return float(np.clip(pred, -MAX_ADJUSTMENT_POINTS, MAX_ADJUSTMENT_POINTS))

    def adjust_means(
        self,
        means: dict[str, float],
        home_feats: dict[str, float],
        away_feats: dict[str, float],
    ) -> dict[str, float]:
        """Apply the residual as a home-margin shift, splitting across both scores."""
        resid = self.predict_residual(home_feats, away_feats)
        if not resid:
            return means
        out = dict(means)
        # Positive residual = home should score relatively more than additive baseline.
        out["mu_home"] = float(means["mu_home"]) + resid / 2.0
        out["mu_away"] = float(means["mu_away"]) - resid / 2.0
        out["mu_home"] = float(np.clip(out["mu_home"], 7.0, 45.0))
        out["mu_away"] = float(np.clip(out["mu_away"], 7.0, 45.0))
        out["model_spread"] = out["mu_away"] - out["mu_home"]
        out["model_total"] = out["mu_home"] + out["mu_away"]
        out["matchup_residual"] = round(resid, 3)
        return out

    def save(self, path: Path | None = None) -> Path:
        p = path or MODEL_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            pickle.dump({"model": self.model, "feature_keys": self.feature_keys}, f)
        return p


def load_adjuster(path: Path | None = None) -> MatchupAdjuster:
    p = path or MODEL_PATH
    if not p.exists():
        return MatchupAdjuster(model=None)
    try:
        with p.open("rb") as f:
            blob = pickle.load(f)
        return MatchupAdjuster(model=blob.get("model"), feature_keys=tuple(blob.get("feature_keys") or MATCHUP_VECTOR_KEYS))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load matchup model (%s) — using no-op adjuster", exc)
        return MatchupAdjuster(model=None)


def _new_regressor() -> Any:
    """LightGBM if available, else sklearn HistGradientBoosting (shallow, regularized)."""
    try:
        import lightgbm as lgb  # type: ignore

        return lgb.LGBMRegressor(
            n_estimators=200,
            num_leaves=15,
            learning_rate=0.03,
            min_child_samples=20,
            subsample=0.8,
            reg_lambda=1.0,
        )
    except Exception:  # noqa: BLE001
        from sklearn.ensemble import HistGradientBoostingRegressor

        return HistGradientBoostingRegressor(
            max_depth=3,
            learning_rate=0.05,
            max_iter=200,
            l2_regularization=1.0,
            min_samples_leaf=20,
        )


def train_adjuster(
    X: list[dict[str, float]],
    y: list[float],
    *,
    feature_keys: tuple[str, ...] = MATCHUP_VECTOR_KEYS,
) -> MatchupAdjuster:
    """Fit the residual model. ``X`` are matchup feature vectors, ``y`` residual margins."""
    if len(X) < MIN_TRAIN_ROWS:
        logger.warning("Only %d training rows (<%d) — matchup model not trained", len(X), MIN_TRAIN_ROWS)
        return MatchupAdjuster(model=None, feature_keys=feature_keys)
    Xm = np.array([[float(row.get(k, 0.0)) for k in feature_keys] for row in X], dtype=float)
    ym = np.array([float(v) for v in y], dtype=float)
    reg = _new_regressor()
    reg.fit(Xm, ym)
    logger.info("Trained matchup adjuster on %d games (%s)", len(X), type(reg).__name__)
    return MatchupAdjuster(model=reg, feature_keys=feature_keys)


def build_training_data(
    seasons: list[int] | None = None,
) -> tuple[list[dict[str, float]], list[float]]:
    """Assemble (feature_vector, residual_margin) rows from nflverse schedules + PBP.

    Residual target = actual home margin − additive model expectation (approximated by the
    scoring-environment baseline + EPA rating differential), so the model learns only the
    *interaction* part on top of the existing additive layer.
    """
    from sharp_scout.data.nflfastr import load_pbp, load_schedules
    from sharp_scout.phase1.ratings import build_power_ratings, matchup_means
    from sharp_scout.phase1.scheme import build_scheme_features

    pbp = load_pbp(seasons)
    if pbp.empty:
        return [], []
    ratings = build_power_ratings(pbp)
    feats = build_scheme_features(pbp, ratings, enrich=True, seasons=seasons)
    sched = load_schedules(seasons)
    if sched.empty:
        return [], []

    X: list[dict[str, float]] = []
    y: list[float] = []
    for _, g in sched.iterrows():
        home, away = g.get("home_team"), g.get("away_team")
        hs, as_ = g.get("home_score"), g.get("away_score")
        if home not in feats or away not in feats:
            continue
        if hs is None or as_ is None or (isinstance(hs, float) and hs != hs):
            continue
        try:
            actual_margin = float(hs) - float(as_)
        except (TypeError, ValueError):
            continue
        means = matchup_means(home, away, ratings)
        additive_margin = means["mu_home"] - means["mu_away"]  # home perspective
        residual = actual_margin - additive_margin
        X.append(matchup_feature_vector(feats[home], feats[away]))
        y.append(residual)
    logger.info("Built %d matchup training rows", len(X))
    return X, y
