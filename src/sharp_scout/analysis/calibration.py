"""Probability calibration — are our 60% picks actually winning 60%?

We compare model win probabilities (``p_true``) to realized outcomes on settled plays and:

* report a **reliability curve** (predicted vs observed per bin) and **Brier score**, and
* fit a **calibrator** (isotonic when we have enough data, else Platt/logistic, else
  identity) that maps raw ``p_true`` → calibrated probability.

The fitted calibrator is persisted to ``data/calibration.json`` in a sklearn-free form
(isotonic knots or Platt coefficients) so it can be applied at pick time without importing
scikit-learn.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np

from sharp_scout.config import DATA_DIR

logger = logging.getLogger(__name__)

CALIBRATION_PATH = DATA_DIR / "calibration.json"

MIN_ISOTONIC = 50
MIN_PLATT = 20


def collect_prediction_outcomes(ledger: dict[str, Any]) -> list[tuple[float, int]]:
    """(p_true, win) pairs from settled side plays with a decided outcome."""
    pairs: list[tuple[float, int]] = []
    for p in ledger.get("plays") or []:
        if p.get("play_type") == "prop" or str(p.get("market") or "").startswith("player_"):
            continue
        status = p.get("status")
        p_true = p.get("p_true")
        if p_true is None or status not in ("win", "loss"):
            continue
        pairs.append((float(p_true), 1 if status == "win" else 0))
    return pairs


def brier_score(pairs: list[tuple[float, int]]) -> float | None:
    if not pairs:
        return None
    return round(sum((p - y) ** 2 for p, y in pairs) / len(pairs), 4)


def reliability_bins(pairs: list[tuple[float, int]], n_bins: int = 10) -> list[dict[str, Any]]:
    if not pairs:
        return []
    bins: list[dict[str, Any]] = []
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        members = [(p, y) for p, y in pairs if (lo <= p < hi or (i == n_bins - 1 and p == hi))]
        if not members:
            continue
        pred = sum(p for p, _ in members) / len(members)
        obs = sum(y for _, y in members) / len(members)
        bins.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": len(members),
                "pred_mean": round(pred, 3),
                "obs_freq": round(obs, 3),
                "gap": round(obs - pred, 3),
            }
        )
    return bins


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def fit_calibrator(pairs: list[tuple[float, int]]) -> dict[str, Any]:
    """Fit an isotonic / Platt / identity calibrator; return a serializable spec."""
    n = len(pairs)
    if n < MIN_PLATT:
        return {"method": "identity", "n": n}

    xs = np.array([p for p, _ in pairs], dtype=float)
    ys = np.array([y for _, y in pairs], dtype=float)

    if n >= MIN_ISOTONIC:
        try:
            from sklearn.isotonic import IsotonicRegression

            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(xs, ys)
            grid = np.linspace(0.0, 1.0, 21)
            preds = iso.predict(grid)
            return {
                "method": "isotonic",
                "n": n,
                "x": [round(float(v), 4) for v in grid],
                "y": [round(float(v), 4) for v in preds],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Isotonic fit failed (%s); falling back to Platt", exc)

    try:
        from sklearn.linear_model import LogisticRegression

        lr = LogisticRegression()
        lr.fit(xs.reshape(-1, 1), ys)
        a = float(lr.coef_[0][0])
        b = float(lr.intercept_[0])
        return {"method": "platt", "n": n, "a": round(a, 6), "b": round(b, 6)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Platt fit failed (%s); using identity", exc)
        return {"method": "identity", "n": n}


def calibrator_from_spec(spec: dict[str, Any]) -> Callable[[float], float]:
    method = spec.get("method", "identity")
    if method == "isotonic" and spec.get("x") and spec.get("y"):
        xp = np.array(spec["x"], dtype=float)
        fp = np.array(spec["y"], dtype=float)

        def _iso(p: float) -> float:
            return float(np.clip(np.interp(p, xp, fp), 0.0, 1.0))

        return _iso
    if method == "platt":
        a = float(spec.get("a", 1.0))
        b = float(spec.get("b", 0.0))

        def _platt(p: float) -> float:
            return float(min(max(_sigmoid(a * p + b), 0.0), 1.0))

        return _platt
    return lambda p: float(p)


def save_calibrator(spec: dict[str, Any], path: Path | None = None) -> Path:
    p = path or CALIBRATION_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, indent=2) + "\n")
    return p


def load_calibrator(path: Path | None = None) -> Callable[[float], float]:
    p = path or CALIBRATION_PATH
    if not p.exists():
        return lambda x: float(x)
    try:
        spec = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return lambda x: float(x)
    return calibrator_from_spec(spec)


def fit_and_save_from_ledger(ledger: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    spec = fit_calibrator(collect_prediction_outcomes(ledger))
    save_calibrator(spec, path)
    logger.info("Calibration: fit %s on %d samples", spec.get("method"), spec.get("n"))
    return spec


def calibration_report(ledger: dict[str, Any]) -> dict[str, Any]:
    pairs = collect_prediction_outcomes(ledger)
    return {
        "n": len(pairs),
        "brier": brier_score(pairs),
        "bins": reliability_bins(pairs),
    }
