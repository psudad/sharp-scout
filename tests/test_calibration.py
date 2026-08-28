"""Probability calibration tests."""

from __future__ import annotations

import random
from pathlib import Path

from sharp_scout.analysis.calibration import (
    brier_score,
    calibration_report,
    calibrator_from_spec,
    collect_prediction_outcomes,
    fit_calibrator,
    load_calibrator,
    reliability_bins,
    save_calibrator,
)


def test_identity_when_too_few_samples():
    spec = fit_calibrator([(0.6, 1), (0.4, 0)])
    assert spec["method"] == "identity"
    cal = calibrator_from_spec(spec)
    assert cal(0.55) == 0.55


def test_brier_and_bins():
    pairs = [(0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)]
    b = brier_score(pairs)
    assert b is not None and b < 0.05
    bins = reliability_bins(pairs, n_bins=10)
    assert bins  # non-empty


def test_fit_and_load_roundtrip(tmp_path: Path):
    # Well-calibrated-ish synthetic data with enough rows to fit a real calibrator.
    random.seed(0)
    pairs = []
    for _ in range(200):
        p = random.random()
        y = 1 if random.random() < p else 0
        pairs.append((p, y))
    spec = fit_calibrator(pairs)
    assert spec["method"] in ("isotonic", "platt")
    path = tmp_path / "calibration.json"
    save_calibrator(spec, path)
    cal = load_calibrator(path)
    v = cal(0.6)
    assert 0.0 <= v <= 1.0


def test_report_from_ledger():
    ledger = {
        "plays": [
            {"market": "spreads", "side": "home", "p_true": 0.6, "status": "win"},
            {"market": "spreads", "side": "away", "p_true": 0.55, "status": "loss"},
            {"market": "player_pass_yds", "side": "over", "p_true": 0.7, "status": "win"},
        ]
    }
    pairs = collect_prediction_outcomes(ledger)
    assert len(pairs) == 2  # prop excluded
    report = calibration_report(ledger)
    assert report["n"] == 2
