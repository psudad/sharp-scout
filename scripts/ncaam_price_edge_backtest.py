#!/usr/bin/env python3
"""Print NCAAM price-edge gate backtest table from the committed ledger."""

from __future__ import annotations

from sharp_scout.ncaam.price_edge_backtest import format_backtest_markdown, run_ledger_backtest


def main() -> None:
    result = run_ledger_backtest(min_edge=0.01)
    print(format_backtest_markdown(result))


if __name__ == "__main__":
    main()
