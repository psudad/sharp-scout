"""NFL simulation totals — sim, blend, and backtest smoke."""

from __future__ import annotations

from pathlib import Path

from sharp_scout.nfl.totals.backtest import choose_blend_weight
from sharp_scout.nfl.totals.blend import blend_total
from sharp_scout.nfl.totals.rates import TeamDriveRates
from sharp_scout.nfl.totals.simulate import simulate_nfl_total


def test_simulate_produces_probabilities_at_line():
    hr = TeamDriveRates("KC", 11.0, 2.0, 0.55, 5.5)
    ar = TeamDriveRates("BUF", 11.0, 2.0, 0.55, 5.5)
    res = simulate_nfl_total(
        home_team="KC",
        away_team="BUF",
        home_rates=hr,
        away_rates=ar,
        market_line=47.5,
        n_sims=2000,
        seed=1,
    )
    assert 30 <= res.sim_median <= 70
    assert res.p_over is not None and 0.0 < res.p_over < 1.0
    assert res.p_under is not None
    assert abs(res.p_over + res.p_under + (res.p_push or 0) - 1.0) < 0.02


def test_blend_weight_never_worse_than_market_mae():
    sims = [44.0, 50.0, 38.0]
    mkt = [45.0, 48.0, 41.0]
    fin = [46.0, 49.0, 40.0]
    w, sim_mae, blend_mae, mkt_mae = choose_blend_weight(sims, mkt, fin)
    assert blend_mae <= mkt_mae + 1e-6
    assert 0.0 <= w <= 1.0
    blended = blend_total(44.0, 45.0, weight_sim=w)
    assert 44.0 <= blended <= 45.0


def test_backtest_metrics_shape():
    """Fast sanity — full walk-forward backtest is run via scripts/nfl_totals_backtest.py."""
    w, sim_mae, blend_mae, mkt_mae = choose_blend_weight([41.0], [44.0], [43.0])
    assert mkt_mae == 1.0
    assert blend_mae <= mkt_mae
    assert 0.0 <= w <= 1.0
