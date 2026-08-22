"""Timestamped line-history store tests."""

from __future__ import annotations

from pathlib import Path

from sharp_scout.data import line_store


def _event(line: float, price: int = -110) -> dict:
    return {
        "event_id": "e1",
        "home_team": "BUF",
        "away_team": "KC",
        "bookmakers": {
            "pinnacle": {
                "is_sharp": True,
                "markets": {
                    "spreads": [
                        {"side": "home", "point": line, "price": price},
                        {"side": "away", "point": -line, "price": price},
                    ]
                },
            }
        },
    }


def test_record_snapshot_dedupes_unchanged(tmp_path: Path):
    p = tmp_path / "lh.json"
    line_store.record_snapshot([_event(-2.5)], path=p)
    line_store.record_snapshot([_event(-2.5)], path=p)  # unchanged → no new sample
    hist = line_store.load_history(p)
    assert len(hist["e1|spreads|home"]) == 1
    line_store.record_snapshot([_event(-3.0)], path=p)  # moved → new sample
    hist = line_store.load_history(p)
    assert len(hist["e1|spreads|home"]) == 2


def test_closing_sample_prefers_before_kickoff(tmp_path: Path):
    history = {
        "e1|spreads|home": [
            {"ts": "2026-09-09T18:00:00+00:00", "book": "pinnacle", "line": -2.5, "price": -110},
            {"ts": "2026-09-09T23:30:00+00:00", "book": "pinnacle", "line": -3.5, "price": -110},
            {"ts": "2026-09-10T02:00:00+00:00", "book": "pinnacle", "line": -7.0, "price": -110},
        ]
    }
    close = line_store.closing_sample(
        "e1", "spreads", "home", kickoff="2026-09-10T00:00:00+00:00", history=history
    )
    assert close is not None
    assert close["line"] == -3.5  # last sample before kickoff, ignores the post-kick -7
