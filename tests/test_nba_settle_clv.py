"""NBA settlement, CLV sanity, horizon logging, long-dog ML rule."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sharp_scout.nba.clv import close_sample_trustworthy, finalize_nba_clv, sanitize_play_clv, summarize_nba_clv
from sharp_scout.nba.game_lines import h2h_longshot_ev_inputs, scan_game_line_opportunities
from sharp_scout.nba.ledger import append_nba_signals, load_nba_ledger
from sharp_scout.nba.settle import settle_nba_ledger, void_plays_outside_horizon
from sharp_scout.utils.odds import expected_value


def test_void_far_future_kickoff_at_log_time():
    ledger = {
        "plays": [
            {
                "id": "x1",
                "status": "paper",
                "created_at": "2026-10-24T14:00:00+00:00",
                "kickoff": "2026-12-26T03:30:00+00:00",
                "away_team": "DEN",
                "home_team": "GSW",
                "market": "totals",
                "side": "under",
                "price": -115,
                "units": 1.0,
                "clv_at": "2026-10-24T14:00:00+00:00",
                "close_price": -110,
                "close_book": "pinnacle",
            }
        ]
    }
    n = void_plays_outside_horizon(ledger, now=datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert n == 1
    p = ledger["plays"][0]
    assert p["status"] == "void"
    assert p["exclude_reason"] == "kickoff_outside_horizon"
    assert p.get("clv_at") is None


def test_append_refuses_kickoff_outside_horizon(tmp_path):
    ledger_path = tmp_path / "nba_ledger.json"
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    result = append_nba_signals(
        [
            {
                "event_id": "christmas",
                "kickoff": future,
                "away_team": "MIA",
                "home_team": "BOS",
                "market": "h2h",
                "side": "home",
                "price": -185,
                "units": 1.0,
                "edge": 0.05,
                "p_true": 0.68,
                "p_mkt": 0.68,
            }
        ],
        path=ledger_path,
    )
    assert result["added"] == 0


def test_close_sample_rejects_extreme_h2h():
    play = {
        "market": "h2h",
        "price": -185,
        "kickoff": "2026-12-25T19:30:00+00:00",
    }
    close = {
        "price": -5000,
        "book": "betfair_ex_eu",
        "ts": "2026-10-24T14:32:33+00:00",
    }
    ok, reason = close_sample_trustworthy(play, close)
    assert not ok
    assert reason in ("implausible_h2h_close", "close_too_early_vs_kickoff")


def test_sanitize_clears_clv_fields():
    play = {
        "close_price": -5000,
        "clv_prob": 0.33,
        "clv_at": "2026-10-24T00:00:00+00:00",
    }
    sanitize_play_clv(play, reason="implausible_h2h_close")
    assert play.get("clv_prob") is None
    assert play["clv_excluded_reason"] == "implausible_h2h_close"


def test_summarize_clv_excludes_sanitized():
    ledger = {
        "plays": [
            {"clv_at": "t", "clv_prob": 0.5, "market": "h2h"},
            {"clv_excluded_reason": "bad", "clv_at": "t", "clv_prob": 0.99},
        ]
    }
    s = summarize_nba_clv(ledger)
    assert s["n_plays_with_clv"] == 1
    assert s["n_clv_excluded"] == 1


def test_settle_side_and_prop_from_fixture_scores():
    ledger = {
        "plays": [
            {
                "id": "t1",
                "status": "paper",
                "event_id": "401909860",
                "kickoff": "2026-10-25T02:10:00+00:00",
                "away_team": "GSW",
                "home_team": "PHX",
                "market": "h2h",
                "side": "away",
                "price": 330,
                "units": 1.0,
            },
            {
                "id": "t2",
                "status": "paper",
                "event_id": "401909860",
                "kickoff": "2026-10-25T02:10:00+00:00",
                "away_team": "GSW",
                "home_team": "PHX",
                "play_type": "prop",
                "player_name": "Gui Santos",
                "market": "player_assists",
                "side": "over",
                "line": 3.5,
                "price": 144,
                "units": 1.0,
            },
        ]
    }
    scores = [
        {
            "event_id": "401909860",
            "away_team": "GSW",
            "home_team": "PHX",
            "away_score": 122,
            "home_score": 131,
        }
    ]
    box = {
        "401909860": {
            "gui santos": {"player_assists": 3.0},
        }
    }

    from sharp_scout.nba import settle as nba_settle

    nba_settle.fetch_espn_nba_box_scores = lambda ids: box  # type: ignore[method-assign]
    out = settle_nba_ledger(ledger, scores=scores, path=Path("/tmp/unused.json"))
    assert out["plays"][0]["status"] == "loss"
    assert out["plays"][1]["status"] == "loss"
    assert out["plays"][1]["prop_result"] == 3.0


def test_long_dog_rule_rejects_plus330_without_enough_ev():
    p_fair = 0.247
    p_used, min_edge = h2h_longshot_ev_inputs(330.0, p_fair)
    edge = expected_value(p_used, 330.0)
    assert edge < min_edge


def test_long_dog_scan_marks_possible_not_qualified():
    ev = {
        "event_id": "dog-test",
        "home_team": "PHX",
        "away_team": "GSW",
        "bookmakers": {
            "fanduel": {
                "markets": {
                    "h2h": [
                        {"side": "away", "price": 330},
                        {"side": "home", "price": -420},
                    ]
                }
            },
            "draftkings": {
                "markets": {
                    "h2h": [
                        {"side": "away", "price": 320},
                        {"side": "home", "price": -410},
                    ]
                }
            },
            "pinnacle": {
                "markets": {
                    "h2h": [
                        {"side": "away", "price": 293},
                        {"side": "home", "price": -360},
                    ]
                }
            },
        },
    }
    opps = [o for o in scan_game_line_opportunities(ev) if o["side"] == "away"]
    assert opps
    assert not any(o.get("qualified") for o in opps)


def test_settle_survives_espn_scores_outage(monkeypatch):
    ledger = {
        "plays": [
            {
                "id": "open1",
                "status": "paper",
                "kickoff": "2020-01-01T00:00:00+00:00",
                "away_team": "BOS",
                "home_team": "NYK",
                "market": "h2h",
                "side": "away",
                "price": 150,
                "units": 1.0,
            }
        ]
    }

    def _boom(**kwargs):
        raise RuntimeError("ESPN down")

    from sharp_scout.nba import settle as nba_settle

    monkeypatch.setattr(nba_settle, "fetch_espn_nba_scores", _boom)
    out = settle_nba_ledger(dict(ledger), scores=None, path=Path("/tmp/nba_settle_test_unused.json"))
    assert out["plays"][0]["status"] == "paper"
    assert out["plays"][0].get("pnl_units") is None


def test_finalize_nba_clv_applies_sanity(tmp_path, monkeypatch):
    from sharp_scout.nba import paths as nba_paths

    hist = {
        "ev1|h2h|home": [
            {
                "ts": "2026-10-24T12:00:00+00:00",
                "book": "betfair_ex_eu",
                "price": -5000,
                "line": None,
            }
        ]
    }
    ledger = {
        "plays": [
            {
                "event_id": "ev1",
                "market": "h2h",
                "side": "home",
                "kickoff": "2026-12-25T19:30:00+00:00",
                "price": -185,
            }
        ]
    }
    monkeypatch.setattr(nba_paths, "NBA_LINE_HISTORY_PATH", tmp_path / "hist.json")
    tmp_path.joinpath("hist.json").write_text(json.dumps(hist))
    finalize_nba_clv(ledger, history=hist)
    assert ledger["plays"][0].get("clv_excluded_reason")
