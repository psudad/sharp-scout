#!/usr/bin/env python3
"""Backfit player-prop projections on history, then fit and report calibrators.

    python scripts/backfit_props.py --seasons 2023 2024 2025

Writes the graded records to artifacts/props_backfit.json, the fitted per-market
calibrators to data/calibration_props.json, and prints a reliability report showing where
the model is over- or under-confident.

Pass --no-save to inspect the report without overwriting the live calibrators.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.analysis.calibration import (  # noqa: E402
    POOLED_KEY,
    brier_score,
    collect_prop_outcomes,
    fit_prop_calibrators,
    load_prop_calibrator,
    prop_calibration_report,
    save_prop_calibrators,
)
from sharp_scout.config import ARTIFACTS_DIR  # noqa: E402
from sharp_scout.props.backfit import run_backfit  # noqa: E402
from sharp_scout.utils.odds import setup_logging  # noqa: E402


def _holdout_check(records: list[dict]) -> None:
    """Fit on every season but the last, then score the last one.

    The reliability curve above is in-sample, so it will always look like the calibrator
    helps. This is the honest test: does the mapping learned on old seasons improve Brier
    on a season it never saw?
    """
    seasons = sorted({r["season"] for r in records})
    if len(seasons) < 2:
        print("\nHoldout check skipped (need at least two seasons)")
        return
    test_season = seasons[-1]
    train = [r for r in records if r["season"] != test_season]
    test = [r for r in records if r["season"] == test_season]

    specs = fit_prop_calibrators(collect_prop_outcomes(train))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "calibration_props.json"
        save_prop_calibrators(specs, path)
        calibrate = load_prop_calibrator(path)

        raw = [(float(r["p_true"]), 1 if r["status"] == "win" else 0) for r in test]
        cal = [
            (calibrate(float(r["p_true"]), str(r["market"])), 1 if r["status"] == "win" else 0)
            for r in test
        ]

    before, after = brier_score(raw), brier_score(cal)
    delta = (before - after) / before * 100 if before else 0.0
    verdict = "improves" if after < before else "does NOT improve"
    print(
        f"\nHoldout ({test_season}, n={len(test)}, trained on {seasons[:-1]}): "
        f"Brier {before} → {after} ({delta:+.1f}%) — calibration {verdict} out of sample"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfit and calibrate player props")
    ap.add_argument("--seasons", type=int, nargs="+", default=None)
    ap.add_argument("--n-sims", type=int, default=2000)
    ap.add_argument(
        "--min-train-weeks",
        type=int,
        default=17,
        help="Weeks of history to accumulate before grading starts",
    )
    ap.add_argument("--no-save", action="store_true", help="Report only; do not write calibrators")
    args = ap.parse_args()

    setup_logging("INFO")
    logging.getLogger("sharp_scout.props.usage").setLevel(logging.WARNING)

    records = run_backfit(
        args.seasons, n_sims=args.n_sims, min_train_weeks=args.min_train_weeks
    )
    if not records:
        raise SystemExit("Backfit produced no graded records")

    out = ARTIFACTS_DIR / "props_backfit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, indent=2, default=str))
    print(f"\nGraded records: {len(records)} → {out}")

    by_market = collect_prop_outcomes(records)
    report = prop_calibration_report(by_market)

    pooled = report["pooled"]
    print(f"\nPooled: n={pooled['n']}  Brier={pooled['brier']}")
    print("\nPer-market bias (model mean vs realized hit rate):")
    print(f"  {'market':24} {'n':>7} {'model':>8} {'actual':>8} {'gap':>8} {'brier':>7}")
    for market, m in report["markets"].items():
        gap = (m["obs_freq"] - m["pred_mean"]) if m["pred_mean"] is not None else 0.0
        print(
            f"  {market.replace('player_', ''):24} {m['n']:>7} "
            f"{m['pred_mean']:>8.3f} {m['obs_freq']:>8.3f} {gap:>+8.3f} {m['brier']:>7}"
        )

    print("\nPooled reliability curve:")
    print(f"  {'bin':>10} {'n':>7} {'predicted':>10} {'observed':>10} {'gap':>8}")
    for b in pooled["bins"]:
        print(
            f"  {b['bin']:>10} {b['n']:>7} {b['pred_mean']:>10.3f} "
            f"{b['obs_freq']:>10.3f} {b['gap']:>+8.3f}"
        )

    _holdout_check(records)

    specs = fit_prop_calibrators(by_market)
    fitted = sorted(k for k in specs if k != POOLED_KEY)
    print(f"\nFitted calibrators: pooled ({specs[POOLED_KEY]['method']})"
          f" + {len(fitted)} per-market")
    for market in fitted:
        print(f"  {market.replace('player_', ''):24} {specs[market]['method']:>9} "
              f"n={specs[market]['n']}")

    if args.no_save:
        print("\n--no-save: calibrators not written")
        return
    path = save_prop_calibrators(specs)
    report_path = ARTIFACTS_DIR / "props_calibration_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nCalibrators: {path}\nReport:      {report_path}")


if __name__ == "__main__":
    main()
