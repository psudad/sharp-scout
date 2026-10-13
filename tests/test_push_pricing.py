"""Push-aware pricing on whole-number lines."""

from __future__ import annotations

import pytest

from sharp_scout.phase2.monte_carlo import p_push_for_market, p_true_for_market, simulate_game


@pytest.fixture(scope="module")
def sim():
    return simulate_game("HOU", "BUF", 23.5, 21.0)


def test_away_whole_line_excludes_push(sim):
    p_home = p_true_for_market(sim, "spreads", "home", -3.0)
    p_away = p_true_for_market(sim, "spreads", "away", 3.0, sport="nfl")
    push = p_push_for_market(sim, "spreads", "away", 3.0, sport="nfl")
    assert push >= 0.151 / 2 - 1e-9  # key-number floor for 3
    assert p_home + p_away + push == pytest.approx(1.0, abs=1e-9)


def test_half_point_lines_have_no_push(sim):
    assert p_push_for_market(sim, "spreads", "away", 3.5, sport="nfl") == 0.0
    assert p_push_for_market(sim, "totals", "under", 44.5) == 0.0
    assert p_push_for_market(sim, "h2h", "home", None) == 0.0


def test_under_whole_total_excludes_push(sim):
    p_over = p_true_for_market(sim, "totals", "over", 44.0)
    p_under = p_true_for_market(sim, "totals", "under", 44.0)
    push = p_push_for_market(sim, "totals", "under", 44.0)
    assert push > 0
    assert p_over + p_under + push == pytest.approx(1.0, abs=1e-9)
