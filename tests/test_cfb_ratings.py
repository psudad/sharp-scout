import pandas as pd
import pytest

from sharp_scout.data.cfbfastr import NON_FBS_POOL, cfb_rating_plays
from sharp_scout.phase1.ratings import TeamPower, matchup_means


def _plays():
    return pd.DataFrame(
        {
            "posteam": ["MEM", "MEM", "MEM", "MEM", "UT MARTIN"],
            "defteam": ["UT MARTIN", "UT MARTIN", "UT MARTIN", "UT MARTIN", "MEM"],
            "home_team": ["MEM"] * 5,
            "away_team": ["UT MARTIN"] * 5,
            "home_team_division": ["fbs"] * 5,
            "away_team_division": ["fcs"] * 5,
            "is_rush": [True, False, False, True, True],
            "is_dropback": [False, True, False, False, False],
            "wp_before": [0.6, 0.7, 0.6, 0.99, 0.4],
            "epa": [0.3, 0.5, -1.8, 0.2, -0.1],
        }
    )


def test_rating_plays_drop_non_scrimmage_and_garbage_time():
    plays, fbs = cfb_rating_plays(_plays())
    assert fbs == {"MEM"}
    # timeout-style row (no rush/dropback) and the wp=0.99 blowout snap are gone
    assert plays["epa"].tolist() == [0.3, 0.5, -0.1]


def test_rating_plays_pool_non_fbs_teams():
    plays, _ = cfb_rating_plays(_plays())
    assert set(plays["posteam"]) == {"MEM", NON_FBS_POOL}
    assert set(plays["defteam"]) == {"MEM", NON_FBS_POOL}


def _tp(team, off, de):
    return TeamPower(team, off, de, 0, 0, 0, 0, 0, 0, off + de)


def test_ncaaf_total_uses_flatter_scale_than_margin():
    ratings = {"A": _tp("A", 0.2, 0.1), "B": _tp("B", -0.1, -0.1)}
    m = matchup_means("A", "B", ratings, home_boost=0.0, sport="ncaaf")
    # margin = 56 * ((0.2+0.1) - (-0.1-0.1)) = 28; total = 53 + 16 * (0.3 - 0.2) = 54.6
    assert m["model_spread"] == pytest.approx(-28.0)
    assert m["model_total"] == pytest.approx(54.6)


def test_explicit_epa_scale_applies_to_margin_and_total():
    ratings = {"KC": _tp("KC", 0.1, 0.05), "LV": _tp("LV", -0.05, 0.0)}
    m = matchup_means("KC", "LV", ratings, home_boost=2.2, sport="nfl", epa_scale=28.0, scoring_base=22.5)
    assert m["mu_home"] == pytest.approx(22.5 + 28.0 * (0.1 - 0.0) + 1.1)
    assert m["mu_away"] == pytest.approx(22.5 + 28.0 * (-0.05 - 0.05) - 1.1)


def test_nfl_margin_and_total_scales():
    ratings = {"KC": _tp("KC", 0.1, 0.05), "LV": _tp("LV", -0.05, 0.0)}
    m = matchup_means("KC", "LV", ratings, home_boost=0.0, sport="nfl")
    # margin = 45 * ((0.1-0.0) - (-0.05-0.05)) = 9; total = 45 + 28 * (0.1 - 0.1) = 45
    assert m["model_spread"] == pytest.approx(-9.0)
    assert m["model_total"] == pytest.approx(45.0)
