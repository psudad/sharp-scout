"""Official Pace of Play ledger (Jason card + auto-append)."""

from __future__ import annotations

from sharp_scout.nba.score_model.official_pace import load_official_pace, summarize_official_pace


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
