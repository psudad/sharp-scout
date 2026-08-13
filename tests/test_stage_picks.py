"""Stage picks comparison tests."""

from __future__ import annotations

from sharp_scout.data.action_network import mock_splits
from sharp_scout.data.odds_api import mock_odds_events
from sharp_scout.phase2.monte_carlo import simulate_game
from sharp_scout.stage_picks import (
    build_game_stage_card,
    pick_money,
    pick_public,
    settle_stage_pick,
    summarize_stage_slate,
)


def test_public_and_money_diverge():
    split = mock_splits()[0]
    pub = pick_public(split, "BUF", "KC")
    mon = pick_money(split, "BUF", "KC")
    assert pub.available and mon.available
    # mock: tickets 72% BUF, money 59% KC
    assert pub.side == "home"
    assert mon.side == "away"


def test_stage_card_has_all_stages():
    ev = mock_odds_events()[0]
    sim = simulate_game("BUF", "KC", 24, 27, n_sims=1000, seed=1)
    card = build_game_stage_card(ev, sim, mock_splits(), [], market="spread")
    d = card.to_dict()
    for stage in ("model", "sharp", "public", "money", "rlm", "hybrid"):
        assert stage in d["picks"]
    assert d["agreement"]["n_available"] >= 3


def test_settle_stage_ats():
    # Home +2.5, final home 20 away 20 → home covers
    assert settle_stage_pick("home", home_score=20, away_score=20, market="spread", line=2.5) == "win"
    assert settle_stage_pick("away", home_score=20, away_score=20, market="spread", line=2.5) == "loss"


def test_summarize():
    ev = mock_odds_events()[0]
    sim = simulate_game("BUF", "KC", 24, 27, n_sims=500, seed=2)
    card = build_game_stage_card(ev, sim, mock_splits(), [], market="spread").to_dict()
    summary = summarize_stage_slate([card])
    assert summary["n_games"] == 1
