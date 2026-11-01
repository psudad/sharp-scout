from sharp_scout.ncaam.model import project_game, simulate_margin, p_cover_side
from sharp_scout.ncaam.ratings import load_ratings
from pathlib import Path


def test_projection_known_torvik_rows():
    ratings = load_ratings(Path("tests/fixtures/ncaam/torvik_sample.csv"))
    duke = ratings["Duke"]
    unc = ratings["North Carolina"]
    proj = project_game(
        home_team="Duke",
        away_team="North Carolina",
        home_ratings=duke,
        away_ratings=unc,
        neutral_site=False,
    )
    assert proj.margin_model != 0
    margins = simulate_margin(proj, n=5000)
    p, push = p_cover_side(margins, "home", -4.5)
    assert 0.05 < p < 0.95
    assert 0 <= push < 0.05
