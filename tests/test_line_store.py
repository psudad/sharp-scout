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


def test_opening_sample_is_first_seen_line(tmp_path: Path):
    p = tmp_path / "lh.json"
    line_store.record_snapshot([_event(-2.5)], path=p)
    line_store.record_snapshot([_event(-3.0)], path=p)
    line_store.record_snapshot([_event(-3.5)], path=p)

    opening = line_store.opening_sample("e1", "spreads", "home", path=p)
    closing = line_store.closing_sample("e1", "spreads", "home", path=p)
    assert opening is not None and closing is not None
    assert opening["line"] == -2.5
    assert closing["line"] == -3.5


def test_backfill_open_lines_uses_line_history(tmp_path: Path, monkeypatch):
    """Open lines must survive across CI runs, otherwise open == current and RLM never fires."""
    from sharp_scout.data import splits_board

    p = tmp_path / "lh.json"
    line_store.record_snapshot([_event(-2.5)], path=p)
    line_store.record_snapshot([_event(-4.0)], path=p)
    history = line_store.load_history(p)
    monkeypatch.setattr(line_store, "load_history", lambda *a, **k: history)

    board = {
        "event_id": "e1",
        "markets": {"spread": {"line": -4.0, "open_line": None}},
    }
    splits_board._backfill_open_lines(board)
    assert board["markets"]["spread"]["open_line"] == -2.5
    assert board["markets"]["spread"]["open_line_book"] == "pinnacle"


def test_prepare_splits_for_filters_backfills_open_before_rlm(tmp_path: Path, monkeypatch):
    """Pipeline must backfill open lines before Phase 4 or RLM never confirms plays."""
    from sharp_scout.data import splits_board
    from sharp_scout.phase3.market import EdgeCandidate
    from sharp_scout.phase4.filters import validate_edge

    p = tmp_path / "lh.json"
    line_store.record_snapshot(
        [
            {
                "event_id": "smu-fsu",
                "home_team": "FSU",
                "away_team": "SMU",
                "bookmakers": {
                    "pinnacle": {
                        "is_sharp": True,
                        "markets": {
                            "spreads": [
                                {"side": "home", "point": 3.0, "price": -110},
                                {"side": "away", "point": -3.0, "price": -110},
                            ]
                        },
                    }
                },
            }
        ],
        path=p,
    )
    line_store.record_snapshot(
        [
            {
                "event_id": "smu-fsu",
                "home_team": "FSU",
                "away_team": "SMU",
                "bookmakers": {
                    "pinnacle": {
                        "is_sharp": True,
                        "markets": {
                            "spreads": [
                                {"side": "home", "point": 2.5, "price": -110},
                                {"side": "away", "point": -2.5, "price": -110},
                            ]
                        },
                    }
                },
            }
        ],
        path=p,
    )
    history = line_store.load_history(p)
    monkeypatch.setattr(line_store, "load_history", lambda *a, **k: history)

    splits = [
        {
            "home_team": "FSU",
            "away_team": "SMU",
            "markets": {
                "spread": {
                    "home_bet_pct": 0.34,
                    "away_bet_pct": 0.66,
                    "home_money_pct": 0.31,
                    "away_money_pct": 0.69,
                    "open_line": None,
                    "current_line": 2.5,
                }
            },
        }
    ]
    events = [{"event_id": "smu-fsu", "home_team": "FSU", "away_team": "SMU"}]

    edge = EdgeCandidate(
        event_id="smu-fsu",
        home_team="FSU",
        away_team="SMU",
        market="spreads",
        side="home",
        line=2.5,
        book="draftkings",
        price=-110,
        p_true=0.76,
        p_mkt=0.55,
        edge=0.04,
        sharp_book="pinnacle",
        sharp_price=-110,
        model_spread=-4.5,
        model_total=54.0,
    )

    fr_raw = validate_edge(edge, splits)
    assert fr_raw.flags["rlm"] is False
    assert any("no open/current line for RLM" in n for n in fr_raw.notes)

    prepared = splits_board.prepare_splits_for_filters(splits, events, sport="ncaaf")
    assert prepared[0]["markets"]["spread"]["open_line"] == 3.0

    fr = validate_edge(edge, prepared)
    assert fr.flags["rlm"] is True
    assert fr.passed is True


def test_prepare_splits_prefers_line_history_over_open_memory(tmp_path: Path, monkeypatch):
    """Stale open_lines.json must not block durable line_history backfill."""
    from sharp_scout.data import line_memory, splits_board

    monkeypatch.setattr(line_memory, "OPEN_LINES_PATH", tmp_path / "open_lines.json")
    line_memory._save({"smu-an|spread": 2.5})

    p = tmp_path / "lh.json"
    line_store.record_snapshot(
        [
            {
                "event_id": "smu-fsu",
                "home_team": "FSU",
                "away_team": "SMU",
                "bookmakers": {
                    "pinnacle": {
                        "is_sharp": True,
                        "markets": {
                            "spreads": [
                                {"side": "home", "point": 3.0, "price": -110},
                                {"side": "away", "point": -3.0, "price": -110},
                            ]
                        },
                    }
                },
            }
        ],
        path=p,
    )
    history = line_store.load_history(p)
    monkeypatch.setattr(line_store, "load_history", lambda *a, **k: history)

    splits = [
        {
            "game_id": "smu-an",
            "home_team": "FSU",
            "away_team": "SMU",
            "markets": {
                "spread": {
                    "home_bet_pct": 0.34,
                    "away_bet_pct": 0.66,
                    "home_money_pct": 0.31,
                    "away_money_pct": 0.69,
                    "open_line": None,
                    "current_line": 2.5,
                }
            },
        }
    ]
    events = [{"event_id": "smu-fsu", "home_team": "FSU", "away_team": "SMU"}]

    prepared = splits_board.prepare_splits_for_filters(splits, events, sport="ncaaf")
    assert prepared[0]["markets"]["spread"]["open_line"] == 3.0
