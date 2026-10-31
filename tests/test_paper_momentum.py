from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sharp_scout.data import line_store
from sharp_scout.nfl.totals import paper_momentum


def test_paper_momentum_logs_first_move(tmp_path: Path, monkeypatch):
    lh = tmp_path / "lh.json"
    paper = tmp_path / "paper.json"
    monkeypatch.setattr(line_store, "LINE_HISTORY_PATH", lh)
    monkeypatch.setattr(paper_momentum, "PAPER_PATH", paper)

    eid = "abc123"
    open_ts = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    scan_ts = datetime(2026, 10, 25, 14, 0, tzinfo=timezone.utc)
    line_store.record_snapshot(
        [
            {
                "event_id": eid,
                "sport": "nfl",
                "home_team": "NYJ",
                "away_team": "MIA",
                "bookmakers": {
                    "pinnacle": {
                        "is_sharp": True,
                        "markets": {
                            "totals": [
                                {"side": "over", "point": 40.0, "price": -110},
                                {"side": "under", "point": 40.0, "price": -110},
                            ]
                        },
                    }
                },
            }
        ],
        path=lh,
        now=open_ts,
    )
    line_store.record_snapshot(
        [
            {
                "event_id": eid,
                "sport": "nfl",
                "home_team": "NYJ",
                "away_team": "MIA",
                "bookmakers": {
                    "pinnacle": {
                        "is_sharp": True,
                        "markets": {
                            "totals": [
                                {"side": "over", "point": 41.0, "price": -110},
                                {"side": "under", "point": 41.0, "price": -110},
                            ]
                        },
                    }
                },
            }
        ],
        path=lh,
        now=scan_ts,
    )
    hist = line_store.load_history(lh)
    n = paper_momentum.record_paper_momentum_scans(
        [{"event_id": eid, "sport": "nfl", "home_team": "NYJ", "away_team": "MIA"}],
        history=hist,
        path=paper,
    )
    assert n == 1
    store = paper_momentum.load_paper_store(paper)
    assert store["entries"][0]["side"] == "over"
