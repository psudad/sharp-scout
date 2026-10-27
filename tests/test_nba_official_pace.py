"""Official Pace of Play ledger (Jason card + auto-append)."""

from __future__ import annotations

from datetime import date

from sharp_scout.nba.score_model.official_pace import (
    last_official_backfill_date_et,
    load_official_pace,
    summarize_official_pace,
    sync_auto_pace_from_paper_store,
)


def test_official_pace_backfill_record():
    store = load_official_pace()
    summary = summarize_official_pace(store)
    assert summary["record"] == "9-2"
    assert summary["n_plays"] == 11
    assert abs(summary["units"] - 6.18) < 0.02
    assert summary["wins"] == 9
    assert summary["losses"] == 2


def test_sync_skips_games_already_on_official_card(tmp_path, monkeypatch):
    from sharp_scout.nba.score_model import official_pace as op

    store = load_official_pace()
    path = tmp_path / "official.json"
    monkeypatch.setattr(op, "OFFICIAL_PATH", path)
    monkeypatch.setattr(op, "OFFICIAL_CSV_PATH", tmp_path / "official.csv")
    op.save_official_pace({"version": 1, "plays": list(store.get("plays") or [])}, path=path)
    paper = {
        "games": [
            {
                "event_id": "x1",
                "away": "LAC",
                "home": "OKC",
                "kickoff": "2026-10-25T23:10:00+00:00",
                "graded": {
                    "actual_margin": 7,
                    "actual_total": 209,
                    "close_spread_home": -16.5,
                    "close_total": 224.5,
                },
                "frozen": {
                    "snapshot": {
                        "margin": 8.63,
                        "total": 223.45,
                        "injury_margin": 8.63,
                        "injury_total": 223.45,
                        "lines": {"consensus_spread_home": -16.5, "consensus_total": 224.5},
                    }
                },
            }
        ]
    }
    n = op.sync_auto_pace_from_paper_store(paper)
    assert n == 0
    assert len(op.load_official_pace(path).get("plays") or []) == 11


def test_official_plays_have_espn_finals():
    store = load_official_pace()
    for p in store.get("plays") or []:
        assert p.get("espn_away_score") is not None
        assert p.get("espn_home_score") is not None
        assert p.get("result") in ("win", "loss")


def test_backfill_through_oct_26_and_was_cha_final():
    store = load_official_pace()
    assert last_official_backfill_date_et(store) == date(2026, 10, 26)
    was_cha = next(p for p in store["plays"] if p["id"] == "pop-20261026-was-cha")
    assert was_cha["away"] == "WAS"
    assert was_cha["espn_away_score"] == 103
    assert was_cha["espn_home_score"] == 110
    summary = summarize_official_pace(store)
    assert summary["date_range_et"] == "2026-10-25 – 2026-10-26"


def test_auto_sync_skips_backfill_dates_and_requires_display_pick(tmp_path, monkeypatch):
    from sharp_scout.nba.score_model import official_pace as op

    store = load_official_pace()
    path = tmp_path / "official.json"
    monkeypatch.setattr(op, "OFFICIAL_PATH", path)
    monkeypatch.setattr(op, "OFFICIAL_CSV_PATH", tmp_path / "official.csv")
    op.save_official_pace({"version": 1, "plays": list(store.get("plays") or [])}, path=path)

    paper = {
        "games": [
            {
                "event_id": "3f57",
                "away": "IND",
                "home": "BKN",
                "kickoff": "2026-10-25T23:00:00+00:00",
                "graded": {
                    "actual_margin": -5,
                    "actual_total": 200,
                    "close_spread_home": 5.5,
                    "close_total": 220.0,
                },
                "frozen": {
                    "snapshot": {
                        "margin": 0,
                        "total": 220,
                        "injury_margin": 0,
                        "injury_total": 220,
                        "lines": {"consensus_spread_home": 5.5, "consensus_total": 220.0},
                    },
                    "pace_display_pick": {
                        "kind": "spread",
                        "pick": "BKN +5.5",
                        "side": "home",
                        "line": 5.5,
                        "gap": 5.5,
                    },
                },
            },
            {
                "event_id": "3354",
                "away": "WAS",
                "home": "CHA",
                "kickoff": "2026-10-26T23:00:00+00:00",
                "graded": {
                    "actual_margin": 7,
                    "actual_total": 213,
                    "close_spread_home": -2.5,
                    "close_total": 230.0,
                },
                "frozen": {
                    "snapshot": {
                        "margin": 5,
                        "total": 225,
                        "injury_margin": 5,
                        "injury_total": 225,
                        "lines": {"consensus_spread_home": -2.5, "consensus_total": 230.0},
                    },
                    "pace_display_pick": {
                        "kind": "spread",
                        "pick": "CHA -2.5",
                        "side": "home",
                        "line": -2.5,
                        "gap": 9.23,
                    },
                },
            },
            {
                "event_id": "oct27",
                "away": "PHI",
                "home": "IND",
                "kickoff": "2026-10-29T00:00:00+00:00",
                "graded": {
                    "actual_margin": 3,
                    "actual_total": 220,
                    "close_spread_home": -1.5,
                    "close_total": 225.0,
                },
                "frozen": {
                    "snapshot": {
                        "margin": 4,
                        "total": 228,
                        "injury_margin": 4,
                        "injury_total": 228,
                        "lines": {"consensus_spread_home": -1.5, "consensus_total": 225.0},
                    },
                    "pace_display_pick": {
                        "kind": "total",
                        "pick": "PHI @ IND: Over 225",
                        "side": "over",
                        "line": 225.0,
                        "gap": 3.0,
                    },
                },
            },
        ]
    }
    n = sync_auto_pace_from_paper_store(paper)
    assert n == 1
    plays = op.load_official_pace(path).get("plays") or []
    assert len(plays) == 12
    auto = [p for p in plays if p.get("source") == "auto_grade"]
    assert len(auto) == 1
    assert auto[0]["date_et"] == "2026-10-28"
    assert auto[0]["market"] == "total"
