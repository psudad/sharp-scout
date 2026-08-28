#!/usr/bin/env python3
"""Walk-forward backtest over the ledger (or a historical records JSON)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.backtest.walk_forward import (  # noqa: E402
    backtest_from_ledger,
    walk_forward,
)
from sharp_scout.ledger.tracker import load_ledger  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Sharp Scout walk-forward backtest")
    p.add_argument("--records-json", type=Path, help="Historical records JSON list")
    p.add_argument("--edge-threshold", type=float, default=0.0)
    p.add_argument("--min-train", type=int, default=20)
    args = p.parse_args()

    if args.records_json:
        records = json.loads(args.records_json.read_text())
        result = walk_forward(records, edge_threshold=args.edge_threshold, min_train=args.min_train)
    else:
        result = backtest_from_ledger(
            load_ledger(), edge_threshold=args.edge_threshold, min_train=args.min_train
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
