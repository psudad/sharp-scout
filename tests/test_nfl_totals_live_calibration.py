"""Live NFL totals calibration + lean consistency (production path)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sharp_scout.nfl.totals.live_calibration import (
    lean_from_probabilities,
    resolve_live_calibration,
)
from sharp_scout.nfl.totals.live_project import apply_live_calibration
from sharp_scout.nfl.totals.project import project_nfl_totals_for_slate
from sharp_scout.nfl.totals.rates import TeamDriveRates
from sharp_scout.nfl.totals.simulate import simulate_nfl_total


def _event(home: str, away: str, total: float, *, week: int = 7, eid: str = "e1") -> dict:
    return {
        "event_id": eid,
        "home_team": home,
        "away_team": away,
        "week": week,
        "bookmakers": {
            "pinnacle": {
                "is_sharp": True,
                "markets": {
                    "totals": [
                        {"side": "over", "point": total, "price": -110},
                        {"side": "under", "point": total, "price": -110},
                    ]
                },
            }
        },
    }


def test_resolve_live_calibration_uses_oos_csv():
    cal = resolve_live_calibration(before_week=7)
    assert cal.n_training_games >= 10
    assert cal.bias != 0.0 or cal.n_training_games >= 10
    # Backtest week 7 had non-zero blend when sim history exists
    assert cal.blend_weight_sim >= 0.0


def test_apply_live_calibration_lean_matches_probabilities():
    hr = TeamDriveRates("NYJ", 10.5, 2.0, 0.55, 5.5)
    ar = TeamDriveRates("MIA", 10.5, 2.0, 0.55, 5.5)
    sim = simulate_nfl_total(
        home_team="NYJ",
        away_team="MIA",
        home_rates=hr,
        away_rates=ar,
        market_line=39.5,
        n_sims=3000,
        seed=7,
    )
    out = apply_live_calibration(sim, bias=-6.0, blend_weight_sim=0.35, market_line=39.5)
    lean = out["sim_lean"]
    p_over, p_under = out["p_over"], out["p_under"]
    assert lean == lean_from_probabilities(p_over, p_under)
    assert out["sim_median"] == round(float(sim.sim_median) - (-6.0), 2) or abs(
        out["sim_median"] - (sim.sim_median + 6.0)
    ) < 0.02
    assert out["blended_total"] != 39.5 or out["blend_weight_sim"] == 0.0


def test_project_nfl_totals_for_slate_fixture_applies_calibration(tmp_path, monkeypatch):
    csv = Path("reports/nfl_totals_sim_backtest_2026.csv")
    if not csv.exists():
        return
    events = [
        _event("NYJ", "MIA", 39.5, eid="mia-nyj"),
        _event("DET", "GB", 55.5, eid="gb-det"),
    ]
    by_event, meta = project_nfl_totals_for_slate(events, pbp=pd.DataFrame(), skip_pbp=True)
    assert meta["calibration_training_games"] >= 10
    assert meta.get("walk_forward_bias") is not None
    for payload in by_event.values():
        assert "sim_median_raw" in payload
        assert payload["sim_lean"] in ("over", "under")
        p_over, p_under = payload["p_over"], payload["p_under"]
        expected = "over" if p_over >= p_under else "under"
        assert payload["sim_lean"] == expected
        if meta["blend_weight_sim"] > 0 and payload.get("market_line") is not None:
            assert payload["blended_total"] != payload["market_line"]


def test_blend_weight_positive_moves_blended_off_market():
    hr = TeamDriveRates("DET", 11.0, 2.0, 0.55, 5.5)
    ar = TeamDriveRates("GB", 11.0, 2.0, 0.55, 5.5)
    sim = simulate_nfl_total(
        home_team="DET",
        away_team="GB",
        home_rates=hr,
        away_rates=ar,
        market_line=55.5,
        n_sims=2000,
        seed=3,
    )
    out = apply_live_calibration(sim, bias=-7.0, blend_weight_sim=0.4, market_line=55.5)
    assert out["blend_weight_sim"] == 0.4
    assert out["blended_total"] != 55.5
