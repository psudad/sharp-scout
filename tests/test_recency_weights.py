"""Recency decay counts football weeks, so last season survives as a prior."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sharp_scout.phase1.ratings import OFFSEASON_GAP_WEEKS, _recency_weights


def _pbp(rows):
    return pd.DataFrame(rows, columns=["season", "week", "game_date"])


def test_prior_season_finale_is_weeks_not_months_ago():
    pbp = _pbp([
        (2025, 1, "2025-09-07"),
        (2025, 18, "2026-01-04"),
        (2026, 1, "2026-09-13"),
        (2026, 2, "2026-09-20"),
    ])
    w = _recency_weights(pbp, half_life_weeks=6.0)
    # 2026 wk2 is "now"; wk1 is one week back.
    assert w[3] == 1.0
    assert np.isclose(w[2], 0.5 ** (1 / 6))
    # 2025 wk18: 0 weeks left in 2025 + offseason gap + 2 weeks into 2026.
    assert np.isclose(w[1], 0.5 ** ((OFFSEASON_GAP_WEEKS + 2) / 6))
    # Calendar decay would have made this ~0.02; football-week decay keeps a real prior.
    assert w[1] > 0.4
    # 2025 wk1 is 17 weeks further back than wk18.
    assert np.isclose(w[0], 0.5 ** ((17 + OFFSEASON_GAP_WEEKS + 2) / 6))


def test_two_seasons_back_includes_full_middle_season():
    pbp = _pbp([(2024, 17, "2024-12-29"), (2025, 17, "2025-12-28"), (2026, 1, "2026-09-13")])
    w = _recency_weights(pbp, half_life_weeks=6.0)
    # 2024 wk17: 0 left in 2024 + all 17 of 2025 + two offseason gaps + 1 week into 2026.
    assert np.isclose(w[0], 0.5 ** ((17 + 2 * OFFSEASON_GAP_WEEKS + 1) / 6))
    assert w[0] < w[1] < w[2] == 1.0


def test_falls_back_to_dates_without_week_columns():
    pbp = pd.DataFrame({"game_date": ["2026-09-06", "2026-09-20"]})
    w = _recency_weights(pbp, half_life_weeks=2.0)
    assert np.isclose(w[0], 0.5) and w[1] == 1.0
