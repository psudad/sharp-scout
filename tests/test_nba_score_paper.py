"""NBA score-model paper track + model filter (offline)."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.nba.score_model.model_filter import alignment_for_play, model_view_for_event
from sharp_scout.nba.score_model.paper import (
    load_paper_store,
    record_score_model_scan,
    save_paper_store,
    summarize_score_paper,
)
from sharp_scout.nba.score_model.engine import V2Engine, V2Params


def _mock_event(
    *,
    eid: str = "ev1",
    home: str = "BOS",
    away: str = "NYK",
) -> dict:
    return {
        "event_id": eid,
        "home_team": home,
        "away_team": away,
        "commence_time": datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc),
        "bookmakers": {
            "pinnacle": {
                "key": "pinnacle",
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -4.5, "price": -110},
                        {"side": "away", "point": 4.5, "price": -110},
                    ],
                    "totals": [
                        {"side": "over", "point": 220.5, "price": -110},
                        {"side": "under", "point": 220.5, "price": -110},
                    ],
                },
            },
            "draftkings": {
                "key": "draftkings",
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -4.5, "price": -108},
                        {"side": "away", "point": 4.5, "price": -112},
                    ],
                    "totals": [
                        {"side": "over", "point": 220.0, "price": -110},
                        {"side": "under", "point": 220.0, "price": -110},
                    ],
                },
            },
        },
    }


def test_model_alignment_spread_agree():
    engine = V2Engine(params=V2Params(), stage=1)
    view = {
        "proj_margin": 6.0,
        "proj_total": 225.0,
        "consensus_spread_home": -4.5,
        "consensus_total": 220.0,
        "model_spread_side": "home",
        "model_total_side": "over",
        "margin_edge_pts": 1.5,
        "total_edge_pts": 5.0,
    }
    play = {"market": "spreads", "side": "home"}
    assert alignment_for_play(play, view)["model_alignment"] == "agree"
    play2 = {"market": "spreads", "side": "away"}
    assert alignment_for_play(play2, view)["model_alignment"] == "disagree"


def test_record_score_model_scan_tmp(tmp_path, monkeypatch):
    store_path = tmp_path / "paper.json"
    monkeypatch.setattr(
        "sharp_scout.nba.score_model.paper.PAPER_PATH",
        store_path,
    )
    engine = V2Engine(params=V2Params(), stage=3)
    ev = _mock_event()
    record_score_model_scan([ev], engine=engine, store=load_paper_store(store_path))
    store = load_paper_store(store_path)
    assert len(store["games"]) == 1
    assert store["games"][0]["scans"]
    snap = store["games"][0]["scans"][0]
    assert "margin" in snap and "p_cover_home_consensus" in snap


def test_summarize_score_paper_empty():
    assert summarize_score_paper({"games": []}) == {"n_graded": 0}


def test_model_view_uses_engine():
    engine = V2Engine(params=V2Params(), stage=1)
    view = model_view_for_event(_mock_event(), engine=engine)
    assert view["proj_margin"] is not None
    assert view["proj_total"] is not None
