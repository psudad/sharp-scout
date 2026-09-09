"""Prop actuals, settlement, and per-market calibration."""

from __future__ import annotations

import pandas as pd
import pytest

from sharp_scout.analysis.calibration import (
    POOLED_KEY,
    collect_prediction_outcomes,
    collect_prop_outcomes,
    fit_prop_calibrators,
    load_prop_calibrator,
    prop_calibration_report,
    save_prop_calibrators,
)
from sharp_scout.data.nflfastr import _normalize_pbp
from sharp_scout.props.actuals import PropActuals, actual_for_market, player_game_stats

QB = "00-0000001"
RB = "00-0000002"
WR = "00-0000003"


def _play(**kw):
    """One PBP row with the columns _normalize_pbp keeps."""
    row = {
        "season": 2025,
        "week": 1,
        "game_id": "2025_01_NE_SEA",
        "posteam": "SEA",
        "home_team": "SEA",
        "away_team": "NE",
        "play_type": "pass",
        "epa": 0.1,
        "pass": 0,
        "rush": 0,
        "qb_scramble": 0,
        "sack": 0,
        "yards_gained": 0,
        "receiver_player_id": None,
        "passer_player_id": None,
        "rusher_player_id": None,
        "complete_pass": 0,
        "receiving_yards": 0,
        "passing_yards": 0,
        "rushing_yards": 0,
        "air_yards": 0,
        "touchdown": 0,
        "pass_touchdown": 0,
        "rush_touchdown": 0,
        "yardline_100": 50,
        "cpoe": 0.0,
    }
    row.update(kw)
    return row


def _completion(yards: float, td: int = 0):
    return _play(
        play_type="pass",
        **{"pass": 1},
        passer_player_id=QB,
        receiver_player_id=WR,
        complete_pass=1,
        receiving_yards=yards,
        passing_yards=yards,
        pass_touchdown=td,
    )


def _carry(yards: float, td: int = 0, scramble: bool = False):
    if scramble:
        # nflverse marks a scramble as a pass play with rush=0 and no passer id.
        return _play(play_type="run", **{"pass": 1}, qb_scramble=1, rusher_player_id=QB,
                     rushing_yards=yards, rush_touchdown=td)
    return _play(play_type="run", **{"rush": 1}, rusher_player_id=RB,
                 rushing_yards=yards, rush_touchdown=td)


@pytest.fixture
def synthetic_pbp() -> pd.DataFrame:
    rows = [
        _completion(20),
        _completion(35, td=1),
        _play(play_type="pass", **{"pass": 1}, passer_player_id=QB, receiver_player_id=WR),
        _carry(6),
        _carry(4, td=1),
        _carry(12, scramble=True),
        _carry(9, scramble=True),
    ]
    return _normalize_pbp(pd.DataFrame(rows))


def test_player_game_stats_totals(synthetic_pbp):
    stats = player_game_stats(synthetic_pbp).set_index("player_id")

    wr = stats.loc[WR]
    assert wr["targets"] == 3
    assert wr["receptions"] == 2
    assert wr["receiving_yards"] == 55
    assert wr["receiving_tds"] == 1
    assert wr["anytime_td"] == 1

    rb = stats.loc[RB]
    assert rb["carries"] == 2
    assert rb["rushing_yards"] == 10
    assert rb["rushing_tds"] == 1

    qb = stats.loc[QB]
    # 3 pass attempts, 55 passing yards, and the two scrambles count as rushing attempts.
    assert qb["attempts"] == 3
    assert qb["passing_yards"] == 55
    assert qb["passing_tds"] == 1
    assert qb["carries"] == 2
    assert qb["rushing_yards"] == 21
    # A scramble must not be double counted as a pass attempt.
    assert qb["anytime_td"] == 0


def test_qb_scramble_counts_as_rush_attempt(synthetic_pbp):
    """nflverse flags scrambles as pass plays with rush=0, which hid most QB rushing."""
    assert "is_rush_attempt" in synthetic_pbp.columns
    scrambles = synthetic_pbp[synthetic_pbp["qb_scramble"] == 1]
    assert len(scrambles) == 2
    assert bool(scrambles["is_rush"].any()) is False
    assert bool(scrambles["is_rush_attempt"].all()) is True


def test_actual_for_market_maps_every_settleable_market(synthetic_pbp):
    stats = player_game_stats(synthetic_pbp).set_index("player_id")
    wr = stats.loc[WR]
    assert actual_for_market(wr, "player_reception_yds") == 55
    assert actual_for_market(wr, "player_receptions") == 2
    assert actual_for_market(wr, "player_anytime_td") == 1
    assert actual_for_market(stats.loc[QB], "player_pass_yds") == 55
    assert actual_for_market(stats.loc[RB], "player_rush_yds") == 10
    assert actual_for_market(wr, "player_not_a_market") is None


def test_prop_actuals_distinguishes_void_from_unknown(synthetic_pbp, monkeypatch):
    monkeypatch.setattr(
        "sharp_scout.props.actuals.name_to_player_ids",
        lambda: {"real receiver": [WR]},
    )
    pa = PropActuals(synthetic_pbp)

    base = {"season": 2025, "week": 1, "away_team": "NE", "home_team": "SEA"}
    assert pa.value_for({**base, "player_name": "Real Receiver", "market": "player_reception_yds"}) == (
        "ok",
        55.0,
    )
    # Player took no snaps in a game we do have — books refund these.
    assert pa.value_for({**base, "player_name": "Absent Guy", "market": "player_reception_yds"})[0] == "void"
    # Game not in play-by-play yet — must stay pending, not be graded as a loss.
    assert pa.value_for(
        {**base, "season": 2026, "player_name": "Real Receiver", "market": "player_reception_yds"}
    )[0] == "unknown"
    # Market we cannot settle.
    assert pa.value_for({**base, "player_name": "Real Receiver", "market": "player_pass_longest"})[0] == "unknown"


def test_prop_settlement_grades_pending_play(tmp_path, synthetic_pbp, monkeypatch):
    from sharp_scout.ledger import tracker

    monkeypatch.setattr(
        "sharp_scout.props.actuals.name_to_player_ids", lambda: {"real receiver": [WR]}
    )
    monkeypatch.setattr(
        "sharp_scout.props.actuals.PropActuals", lambda *a, **k: PropActuals(synthetic_pbp)
    )

    ledger_path = tmp_path / "ledger.json"
    over = {
        "id": "a",
        "play_type": "prop",
        "status": "pending",
        "season": 2025,
        "week": 1,
        "away_team": "NE",
        "home_team": "SEA",
        "kickoff": "2025-09-07T17:00:00+00:00",
        "player_name": "Real Receiver",
        "market": "player_reception_yds",
        "side": "over",
        "line": 40.5,
        "price": -110,
        "units": 1.0,
    }
    under = {**over, "id": "b", "side": "under"}
    tracker.save_ledger({"plays": [over, under]}, ledger_path)

    tracker.settle_from_scores(
        [
            {
                "season": 2025,
                "week": 1,
                "away_team": "NE",
                "home_team": "SEA",
                "home_score": 24,
                "away_score": 20,
            }
        ],
        path=ledger_path,
    )
    graded = {p["id"]: p for p in tracker.load_ledger(ledger_path)["plays"]}
    # Actual was 55 yards.
    assert graded["a"]["status"] == "win"
    assert graded["a"]["prop_result"] == 55.0
    assert graded["b"]["status"] == "loss"
    assert graded["a"]["pnl_units"] > 0
    assert graded["b"]["pnl_units"] == -1.0


def test_side_calibration_still_ignores_props():
    ledger = {
        "plays": [
            {"p_true": 0.6, "status": "win", "market": "spreads"},
            {"p_true": 0.7, "status": "win", "play_type": "prop", "market": "player_pass_yds"},
        ]
    }
    assert collect_prediction_outcomes(ledger) == [(0.6, 1)]


def test_collect_prop_outcomes_groups_by_market():
    records = [
        {"play_type": "prop", "market": "player_pass_yds", "p_true": 0.6, "status": "win"},
        {"play_type": "prop", "market": "player_pass_yds", "p_true": 0.4, "status": "loss"},
        {"play_type": "prop", "market": "player_receptions", "p_true": 0.55, "status": "win"},
        # Pending and void carry no signal.
        {"play_type": "prop", "market": "player_receptions", "p_true": 0.5, "status": "void"},
        {"market": "spreads", "p_true": 0.6, "status": "win"},
    ]
    by_market = collect_prop_outcomes(records)
    assert set(by_market) == {"player_pass_yds", "player_receptions"}
    assert by_market["player_pass_yds"] == [(0.6, 1), (0.4, 0)]
    assert by_market["player_receptions"] == [(0.55, 1)]


def test_prop_calibrator_falls_back_pooled_then_identity(tmp_path):
    # An over-confident market: the model says 80%, it happens 50%.
    pairs = [(0.8, 1), (0.8, 0)] * 40
    specs = fit_prop_calibrators({"player_pass_yds": pairs}, min_samples=10)
    assert "player_pass_yds" in specs
    assert POOLED_KEY in specs

    path = tmp_path / "calibration_props.json"
    save_prop_calibrators(specs, path)
    calibrate = load_prop_calibrator(path)

    # Fitted market is pulled toward the realized rate.
    assert calibrate(0.8, "player_pass_yds") < 0.75
    # Unknown market still gets calibrated, via the pooled curve.
    assert calibrate(0.8, "player_rush_yds") < 0.75
    # Nothing fit yet → identity, so an unfit deploy cannot silently distort probabilities.
    identity = load_prop_calibrator(tmp_path / "missing.json")
    assert identity(0.8, "player_pass_yds") == 0.8


def test_prop_calibration_report_surfaces_bias():
    by_market = {"player_reception_yds": [(0.7, 0)] * 30 + [(0.7, 1)] * 10}
    report = prop_calibration_report(by_market)
    m = report["markets"]["player_reception_yds"]
    assert m["n"] == 40
    assert m["pred_mean"] == 0.7
    assert m["obs_freq"] == 0.25
    assert report["pooled"]["brier"] is not None
