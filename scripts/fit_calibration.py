#!/usr/bin/env python3
"""Fit the probability calibrator from the settled ledger and save calibration.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.analysis.calibration import (  # noqa: E402
    calibration_report,
    fit_and_save_from_ledger,
)
from sharp_scout.ledger.tracker import load_ledger  # noqa: E402


def main() -> None:
    ledger = load_ledger()
    spec = fit_and_save_from_ledger(ledger)
    report = calibration_report(ledger)
    print(json.dumps({"calibrator": spec, "report": report}, indent=2))


if __name__ == "__main__":
    main()
