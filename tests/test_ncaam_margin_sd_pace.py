import math

import numpy as np

from sharp_scout.ncaam.margin_sd_pace import (
    DEFAULT_REF_POSSESSIONS,
    fit_sqrt_pace_base,
    margin_sd_sqrt_pace,
    p_cover_spread_normal,
)
from sharp_scout.ncaam.model import project_game, simulate_margin
from sharp_scout.ncaam.ratings import load_ratings
from pathlib import Path
from sharp_scout.phase3.market import shift_prob_to_line


def test_margin_sd_scales_with_sqrt_pace():
    slow = margin_sd_sqrt_pace(64.0, base=10.481)
    fast = margin_sd_sqrt_pace(72.0, base=10.481)
    assert fast > slow
    assert abs(slow - 10.481 * math.sqrt(64 / DEFAULT_REF_POSSESSIONS)) < 1e-6


def test_p_cover_matches_normal_sampling():
    mu, sd, line = 3.5, 11.0, -4.5
    p_analytic, _ = p_cover_spread_normal(mu, line, "home", sd)
    draws = np.random.default_rng(0).normal(mu, sd, size=80_000)
    p_mc = float(np.mean(draws + line > 0))
    assert abs(p_analytic - p_mc) < 0.02


def test_shift_prob_roundtrip_with_pace_sd():
    p_ref = 0.52
    ref_line = -3.5
    offer = -4.5
    sd = margin_sd_sqrt_pace(70.0)
    p_shift, gain = shift_prob_to_line(
        p_ref, market="spreads", side="home", ref_line=ref_line, line=offer, sd=sd
    )
    assert gain == offer - ref_line
    assert 0.02 < p_shift < 0.98


def test_fit_sqrt_pace_base_improves_on_synthetic_pace_heterogeneity():
    rng = np.random.default_rng(42)
    poss = rng.uniform(62, 74, size=400)
    spread = rng.uniform(-14, 14, size=400)
    sd_true = 10.5 * np.sqrt(poss / DEFAULT_REF_POSSESSIONS)
    # μ = 0 market
    covered = (rng.normal(0, 1, size=400) * sd_true + spread > 0).astype(int)
    params, _ = fit_sqrt_pace_base(poss, [0.0] * 400, spread, covered)
    assert 9.5 < params.base < 11.5


def test_simulate_margin_respects_custom_sd():
    ratings = load_ratings(Path("tests/fixtures/ncaam/torvik_sample.csv"))
    proj = project_game(
        home_team="Duke",
        away_team="North Carolina",
        home_ratings=ratings["Duke"],
        away_ratings=ratings["North Carolina"],
        neutral_site=False,
    )
    sd = 13.0
    m = simulate_margin(proj, n=5000, sd=sd, rng=np.random.default_rng(1))
    assert abs(float(np.std(m)) - sd) < 0.8
