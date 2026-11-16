#!/usr/bin/env python3
"""Print NCAAM model-agreement gate backtest from the committed ledger."""

from __future__ import annotations

from sharp_scout.ncaam.model_agreement_backtest import (
    format_backtest_markdown,
    run_model_agreement_backtest,
)


def main() -> None:
    result = run_model_agreement_backtest()
    print(format_backtest_markdown(result))


if __name__ == "__main__":
    main()