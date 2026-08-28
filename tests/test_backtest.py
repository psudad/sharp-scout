"""Walk-forward backtest tests."""

from __future__ import annotations

from sharp_scout.backtest.walk_forward import records_from_ledger, walk_forward


def test_walk_forward_basic_metrics():
    records = []
    for week in range(1, 6):
        for i in range(10):
            outcome = "win" if i % 2 == 0 else "loss"
            records.append(
                {
                    "season": 2026,
                    "week": week,
                    "p_true": 0.6 if outcome == "win" else 0.55,
                    "price": -110,
                    "outcome": outcome,
                    "units": 1.0,
                }
            )
    result = walk_forward(records, edge_threshold=-1.0, min_train=10)  # take everything
    assert result["n_weeks"] == 5
    assert result["record"].startswith("25-25")
    assert len(result["weeks"]) == 5
    assert result["win_pct"] == 0.5


def test_records_from_ledger_filters_props_and_pending():
    ledger = {
        "plays": [
            {"season": 2026, "week": 1, "market": "spreads", "side": "home", "p_true": 0.6, "price": -110, "status": "win"},
            {"season": 2026, "week": 1, "market": "player_pass_yds", "side": "over", "p_true": 0.6, "status": "win"},
            {"season": 2026, "week": 1, "market": "totals", "side": "over", "p_true": 0.6, "status": "pending"},
        ]
    }
    recs = records_from_ledger(ledger)
    assert len(recs) == 1  # prop + pending excluded
    assert recs[0]["outcome"] == "win"
