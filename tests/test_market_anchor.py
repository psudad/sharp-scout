"""Calibrated sim variance, market-anchored p_true, and NFL QB adjustment wiring."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sharp_scout.phase1.ratings import (
    TeamPower,
    apply_qb_adjustment,
    backups_from_inactives,
    current_qb_starters,
    qb_short_name,
)
from sharp_scout.phase2.monte_carlo import _sample_scores, score_noise_params, simulate_game
from sharp_scout.phase3.market import anchor_probability, discover_edges, shift_prob_to_line
from sharp_scout.sports import NCAAF, NFL


def test_score_noise_reproduces_target_sds():
    rng = np.random.default_rng(1)
    h, a = _sample_scores(22.5, 22.5, 60_000, rng=rng, margin_sd=13.5, total_sd=13.5)
    assert abs(np.std(h - a) - 13.5) < 0.8
    assert abs(np.std(h + a) - 13.5) < 0.8
    s_h, s_a, rho = score_noise_params(27.5, 27.5, 17.0, 17.0)
    assert abs(s_h - s_a) < 1e-9 and abs(rho) < 1e-9


def test_sim_with_sport_is_less_confident_than_legacy():
    legacy = simulate_game("H", "A", 26.0, 22.0, n_sims=20_000, spread_keys=[-4.0, 3.5])
    nfl = simulate_game("H", "A", 26.0, 22.0, n_sims=20_000, spread_keys=[-4.0, 3.5], sport="nfl")
    # Model says home by 4; P(home covers -4) ~ 50% either way, but a +3.5 dog line
    # (home covering -3.5 means winning by 4+) should be much closer to 50% with real variance.
    assert abs(nfl.cover_probs[-4.0] - 0.5) < 0.05
    assert nfl.cover_probs[3.5] < legacy.cover_probs[3.5]
    assert 0.6 < nfl.cover_probs[3.5] < 0.75


def test_shift_prob_to_line_rewards_better_number():
    p, gain = shift_prob_to_line(0.5, market="spreads", side="away", ref_line=6.5, line=7.5, sd=13.5)
    assert gain == 1.0 and 0.52 < p < 0.54
    p_over, g = shift_prob_to_line(0.5, market="totals", side="over", ref_line=44.5, line=43.5, sd=13.5)
    assert g == 1.0 and p_over > 0.5
    p_under, g = shift_prob_to_line(0.5, market="totals", side="under", ref_line=44.5, line=43.5, sd=13.5)
    assert g == -1.0 and p_under < 0.5
    assert shift_prob_to_line(0.6, market="h2h", side="home", ref_line=None, line=None, sd=13.5) == (0.6, 0.0)


def test_anchor_probability_is_bounded_tilt():
    assert anchor_probability(0.9, 0.5, 0.3) == 0.62
    assert anchor_probability(0.9, None, 0.3) == 0.9


def _event(sharp_pt: float, soft_pt: float):
    return {
        "event_id": "e1", "home_team": "TULSA", "away_team": "ETAM",
        "bookmakers": {
            "pinnacle": {"key": "pinnacle", "is_sharp": True, "markets": {"spreads": [
                {"side": "away", "price": -110, "point": sharp_pt}, {"side": "home", "price": -110, "point": -sharp_pt}]}},
            "soft": {"key": "soft", "is_sharp": False, "markets": {"spreads": [
                {"side": "away", "price": -110, "point": soft_pt}, {"side": "home", "price": -110, "point": -soft_pt}]}},
        },
    }


def test_discover_edges_anchors_to_sharp_and_caps_model_fantasy():
    # Model thinks it's a pick'em; market has the dog +33.5. Old behaviour: p_true≈0.99.
    sim = simulate_game("TULSA", "ETAM", 27.0, 25.0, n_sims=8_000, spread_keys=[-33.5, 33.5, -41.5, 41.5], sport="ncaaf")
    edges = discover_edges(_event(33.5, 41.5), sim, ev_threshold=-1.0, sport="ncaaf")
    away_soft = next(e for e in edges if e.book == "soft" and e.side == "away")
    assert away_soft.p_model > 0.9
    assert away_soft.line_gain == 8.0
    # p_fair: 50% at +33.5 shifted 8 pts at sd 17 → ~68%; anchored with k=0.3 → ~75%, not 99%.
    assert 0.65 < away_soft.p_fair < 0.72
    assert away_soft.p_true < 0.8
    assert abs(away_soft.p_mkt - away_soft.p_fair) < 1e-3


def test_qb_helpers_and_adjustment():
    assert qb_short_name("Caleb Williams") == "C.Williams"
    assert qb_short_name("Jaxson Dart") == "J.Dart"
    pbp = pd.DataFrame({
        "posteam": ["CHI"] * 6 + ["NYG"] * 3,
        "game_id": ["g1", "g1", "g2", "g2", "g3", "g3", "h1", "h1", "h2"],
        "game_date": pd.to_datetime(["2026-09-06"] * 2 + ["2026-09-13"] * 2 + ["2026-09-20"] * 2 + ["2026-09-06"] * 2 + ["2026-09-13"]),
        "is_dropback": [True] * 9,
        "passer_player_name": ["C.Williams", "C.Williams", "C.Williams", "T.Bagent", "C.Williams", "C.Williams", "J.Dart", "J.Dart", "R.Wilson"],
        "epa": [0.1] * 9,
    })
    starters = current_qb_starters(pbp)
    assert starters == {"CHI": "C.Williams", "NYG": "J.Dart"}
    backups = backups_from_inactives(starters, ["Caleb Williams", "Some Receiver"])
    assert backups == {"CHI": True}
    ratings = {"CHI": TeamPower("CHI", 0.05, 0.0, 0, 0, 0, 0, qb_starter_epa=0.12, qb_backup_epa=-0.08, power=0.05)}
    adj = apply_qb_adjustment(ratings, backups)
    assert abs(adj["CHI"].off_epa - (0.05 - 0.20)) < 1e-9
    assert abs(adj["CHI"].power - (0.05 - 0.20)) < 1e-9


def test_sport_configs_carry_anchor_params():
    assert NFL.margin_sd == 13.5 and NCAAF.margin_sd == 17.0
    assert NCAAF.anchor_k_total > NCAAF.anchor_k_spread
    assert NCAAF.spread_model_line_gap > NFL.spread_model_line_gap
