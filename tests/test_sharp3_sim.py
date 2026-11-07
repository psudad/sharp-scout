"""Sharp 3 Monte Carlo projection (replaces fabricated sim_rec)."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import numpy as np
import pytest

from sharp_scout.ncaam import sharp3
from sharp_scout.ncaam.ratings import load_ratings
from sharp_scout.ncaam.rules import RULES
from sharp_scout.ncaam.sharp3_sim import format_sim_rec, monte_carlo_projection


FIXTURE_RATINGS = load_ratings(Path("tests/fixtures/ncaam/torvik_sample.csv"))


def test_sharp3_module_has_no_random_sim_record():
    src = inspect.getsource(importlib.import_module("sharp_scout.ncaam.sharp3"))
    assert "sim_record" not in src
    assert "random.Random" not in src


def test_monte_carlo_unavailable_without_ratings():
    game = {"espn_id": "1", "home_team": "Duke", "away_team": "North Carolina"}
    out = monte_carlo_projection(
        game, side="home", market="spreads", line=-4.5, ratings=None
    )
    assert out["status"] == "unavailable"
    assert format_sim_rec(out) is None


def test_monte_carlo_unavailable_missing_team_ratings():
    game = {"espn_id": "2", "home_team": "Duke", "away_team": "Not A Real Team XYZ"}
    out = monte_carlo_projection(
        game, side="home", market="spreads", line=-4.5, ratings=FIXTURE_RATINGS
    )
    assert out["status"] == "unavailable"
    assert out["reason"] == "missing_team_ratings"


def test_monte_carlo_deterministic_and_counts_sum_to_n():
    game = {"espn_id": "401", "home_team": "Duke", "away_team": "North Carolina", "neutral_site": False}
    n = 2000
    a = monte_carlo_projection(
        game, side="home", market="spreads", line=-4.5, ratings=FIXTURE_RATINGS, n=n
    )
    b = monte_carlo_projection(
        game, side="home", market="spreads", line=-4.5, ratings=FIXTURE_RATINGS, n=n
    )
    assert a == b
    assert a["status"] == "ok"
    assert a["n"] == n
    assert a["wins"] + a["losses"] + a["pushes"] == n
    assert a["model"] == "torvik-efficiency-mc-v1"
    assert a["margin_sd"] == RULES.margin_sd
    rec = format_sim_rec(a)
    assert rec is not None and rec.startswith("proj ")
    assert str(n) in rec


def _splits(h_money, h_tick, a_money, a_tick, hline=-3.5):
    return {
        "spread": {
            "home": {"money_pct": h_money, "ticket_pct": h_tick, "line": hline, "price": -110.0},
            "away": {"money_pct": a_money, "ticket_pct": a_tick, "line": -hline, "price": -110.0},
        },
        "ml": {},
        "splits_source": "test",
    }


def test_evaluate_attaches_real_sim_not_conf_bernoulli():
    game = {
        "espn_id": "99",
        "home_team": "Duke",
        "away_team": "North Carolina",
        "neutral_site": False,
    }
    event = {
        "bookmakers": {
            "draftkings": {
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -4.5, "price": -110},
                        {"side": "away", "point": 4.5, "price": -110},
                    ]
                }
            }
        }
    }
    sp = _splits(30, 40, 70, 30, hline=-4.5)
    with_ratings = sharp3.evaluate(
        game, sp, event, is_mid_major_by_side={"home": False, "away": False}, ratings=FIXTURE_RATINGS
    )
    no_ratings = sharp3.evaluate(
        game, sp, event, is_mid_major_by_side={"home": False, "away": False}, ratings=None
    )
    assert with_ratings["sim_projection"]["status"] == "ok"
    assert with_ratings["sim_rec"] and with_ratings["sim_rec"].startswith("proj ")
    assert no_ratings["sim_rec"] is None
    assert no_ratings["sim_projection"]["status"] == "unavailable"
    # Old fabricated pattern tied conf to ~1000 Bernoulli draws (e.g. 978-22 at extreme conf).
    assert with_ratings["sim_rec"] != f"{int(round(with_ratings['conf'] * RULES.mc_sims))}-{RULES.mc_sims - int(round(with_ratings['conf'] * RULES.mc_sims))}"


def test_sim_projection_not_tied_to_splits_confidence():
    game = {"espn_id": "77", "home_team": "Duke", "away_team": "North Carolina"}
    event = {
        "bookmakers": {
            "draftkings": {
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -10.0, "price": -110},
                        {"side": "away", "point": 10.0, "price": -110},
                    ]
                }
            }
        }
    }
    sp_hi = _splits(80, 20, 20, 80, hline=-10.0)
    sp_lo = _splits(55, 45, 45, 55, hline=-10.0)
    a = sharp3.evaluate(game, sp_hi, event, is_mid_major_by_side={"home": False, "away": False}, ratings=FIXTURE_RATINGS)
    b = sharp3.evaluate(game, sp_lo, event, is_mid_major_by_side={"home": False, "away": False}, ratings=FIXTURE_RATINGS)
    assert a["conf"] != pytest.approx(b["conf"])
    assert a["sim_projection"] == b["sim_projection"]
