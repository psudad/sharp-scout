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
# Props are calibrated separately, and per market: a pass-yards projection and an
# anytime-TD projection are wrong in different directions, so one pooled curve would
# average away both biases.
PROP_CALIBRATION_PATH = DATA_DIR / "calibration_props.json"
POOLED_KEY = "__pooled__"

MIN_ISOTONIC = 50
MIN_PLATT = 20


def _is_prop(play: dict[str, Any]) -> bool:
    return play.get("play_type") == "prop" or str(play.get("market") or "").startswith("player_")


def collect_prediction_outcomes(ledger: dict[str, Any]) -> list[tuple[float, int]]:
    """(p_true, win) pairs from settled side plays with a decided outcome."""
    pairs: list[tuple[float, int]] = []
    for p in ledger.get("plays") or []:
        if _is_prop(p):
            continue
        status = p.get("status")
        p_true = p.get("p_true")
        if p_true is None or status not in ("win", "loss"):
            continue
        pairs.append((float(p_true), 1 if status == "win" else 0))
    return pairs


def collect_prop_outcomes(records: Any) -> dict[str, list[tuple[float, int]]]:
    """(p_true, win) pairs from decided prop plays, grouped by market.

    Accepts either a ledger dict or a bare list of graded records, so the same fitting
    path serves live settled plays and the historical backfit.
    """
    plays = records.get("plays") or [] if isinstance(records, dict) else list(records or [])
    by_market: dict[str, list[tuple[float, int]]] = {}
    for p in plays:
        if not _is_prop(p):
            continue
        status = p.get("status") or p.get("outcome")
        p_true = p.get("p_true")
        if p_true is None or status not in ("win", "loss"):
            continue
        market = str(p.get("market") or "unknown")
        by_market.setdefault(market, []).append((float(p_true), 1 if status == "win" else 0))
    return by_market


def fit_prop_calibrators(
    by_market: dict[str, list[tuple[float, int]]],
    *,
    min_samples: int = MIN_ISOTONIC,
) -> dict[str, dict[str, Any]]:
    """Fit one calibrator per market, plus a pooled fallback for thin markets."""
    pooled_pairs = [pair for pairs in by_market.values() for pair in pairs]
    specs: dict[str, dict[str, Any]] = {POOLED_KEY: fit_calibrator(pooled_pairs)}
    for market, pairs in by_market.items():
        if len(pairs) < min_samples:
            logger.info(
                "Calibration: %s has %d samples (< %d) — using pooled curve",
                market,
                len(pairs),
                min_samples,
            )
            continue
        specs[market] = fit_calibrator(pairs)
    return specs


def save_prop_calibrators(specs: dict[str, dict[str, Any]], path: Path | None = None) -> Path:
    p = path or PROP_CALIBRATION_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(specs, indent=2) + "\n")
    return p


def load_prop_calibrator(path: Path | None = None) -> Callable[[float, str], float]:
    """Returns calibrate(p_true, market) → calibrated probability.

    Falls back to the pooled curve for a market without its own fit, and to identity when
    nothing has been fit yet.
    """
    p = path or PROP_CALIBRATION_PATH
    specs: dict[str, dict[str, Any]] = {}
    if p.exists():
        try:
            specs = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            specs = {}
    cache: dict[str, Callable[[float], float]] = {}

    def _calibrate(p_true: float, market: str) -> float:
        key = market if market in specs else POOLED_KEY
        if key not in cache:
            cache[key] = calibrator_from_spec(specs.get(key) or {"method": "identity"})
        return cache[key](float(p_true))

    return _calibrate


def prop_calibration_report(by_market: dict[str, list[tuple[float, int]]]) -> dict[str, Any]:
    """Reliability curve and Brier score per market, plus pooled."""
    pooled = [pair for pairs in by_market.values() for pair in pairs]
    return {
        "pooled": {
            "n": len(pooled),
            "brier": brier_score(pooled),
            "bins": reliability_bins(pooled),
        },
        "markets": {
            market: {
                "n": len(pairs),
                "brier": brier_score(pairs),
                # Mean model probability vs realized hit rate is the headline bias number.
                "pred_mean": round(sum(p for p, _ in pairs) / len(pairs), 4) if pairs else None,
                "obs_freq": round(sum(y for _, y in pairs) / len(pairs), 4) if pairs else None,
                "bins": reliability_bins(pairs),
            }
            for market, pairs in sorted(by_market.items())
        },
    }


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
