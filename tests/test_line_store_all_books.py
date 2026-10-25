"""Multi-book line history recording."""

from __future__ import annotations

from pathlib import Path

from sharp_scout.data import line_store


def _event_with_retail() -> dict:
    return {
        "event_id": "live-e1",
        "bookmakers": {
            "pinnacle": {
                "is_sharp": True,
                "markets": {
                    "totals": [
                        {"side": "over", "point": 44.5, "price": -110},
                        {"side": "under", "point": 44.5, "price": -110},
                    ],
                    "spreads": [
                        {"side": "home", "point": 3.0, "price": -110},
                        {"side": "away", "point": -3.0, "price": -110},
                    ],
                    "h2h": [
                        {"side": "home", "point": None, "price": 150},
                        {"side": "away", "point": None, "price": -170},
                    ],
                },
            },
            "draftkings": {
                "is_sharp": False,
                "markets": {
                    "totals": [
                        {"side": "over", "point": 45.0, "price": -105},
                        {"side": "under", "point": 45.0, "price": -115},
                    ],
                },
            },
        },
    }


def test_record_snapshot_stores_retail_totals(tmp_path: Path, monkeypatch):
    p = tmp_path / "lh.json"
    monkeypatch.setattr(line_store, "LINE_HISTORY_PATH", p)
    line_store.record_snapshot([_event_with_retail()], path=p, sharp_only=False)
    hist = line_store.load_history(p)
    over = hist["live-e1|totals|over"]
    books = {s["book"] for s in over}
    assert "pinnacle" in books
    assert "draftkings" in books


def test_record_snapshot_skips_demo_event(tmp_path: Path):
    p = tmp_path / "lh.json"
    from sharp_scout.data.odds_api import mock_odds_events

    line_store.record_snapshot(mock_odds_events(), path=p, skip_demo_events=True)
    assert line_store.load_history(p) == {}
