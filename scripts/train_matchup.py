#!/usr/bin/env python3
"""Train the matchup-interaction residual model from nflverse history and save it.

Requires play-by-play + schedules (downloads from nflverse). Uses scikit-learn gradient
boosting by default; LightGBM if installed (`pip install -e ".[ml]"`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.phase1.matchup_ml import (  # noqa: E402
    MODEL_PATH,
    build_training_data,
    train_adjuster,
)


def main() -> None:
    p = argparse.ArgumentParser(description="Train Sharp Scout matchup engine")
    p.add_argument("--season", type=int, action="append", default=None, help="Repeatable")
    args = p.parse_args()

    X, y = build_training_data(args.season)
    adjuster = train_adjuster(X, y)
    if not adjuster.ready:
        print(json.dumps({"trained": False, "rows": len(X), "reason": "insufficient data"}, indent=2))
        return
    path = adjuster.save()
    print(json.dumps({"trained": True, "rows": len(X), "model_path": str(path or MODEL_PATH)}, indent=2))


if __name__ == "__main__":
    main()
