"""NBA score-model paper grading (settle path)."""

from __future__ import annotations

from unittest.mock import patch

from sharp_scout.nba.score_model import paper as paper_mod


def test_grade_score_model_paper_without_freeze_imports_true_close():
    """Regression: grade must not rely on freeze_and_close_lines importing true_close."""
    store = {
        "games": [
            {
                "away": "GSW",
                "home": "HOU",
                "kickoff": "2026-11-12T02:40:00+00:00",
                "scans": [
                    {
                        "at": "2026-11-11T20:00:00+00:00",
                        "margin": 3.0,
                        "total": 220.0,
                        "lines": {"consensus_spread_home": -5.0, "consensus_total": 222.5},
                    }
                ],
            }
        ]
    }
    scores = [{"away_team": "GSW", "home_team": "HOU", "home_score": 110, "away_score": 100}]
    with (
        patch.object(paper_mod, "freeze_and_close_lines", return_value=0),
        patch.object(paper_mod, "void_score_paper_outside_horizon"),
        patch.object(paper_mod, "save_paper_store"),
        patch.object(paper_mod, "dedupe_paper_games_by_matchup", side_effect=lambda s: 0),
    ):
        out = paper_mod.grade_score_model_paper(scores=scores, store=store)
    assert out["games"][0].get("graded")
