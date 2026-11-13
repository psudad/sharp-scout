"""Tests for Nov 2026 NCAAM readiness fixes (ML anchor, CLV, daily Torvik)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sharp_scout.ledger.clv import finalize_closing_lines
from sharp_scout.ncaam import ratings as ratings_mod
from sharp_scout.ncaam.candidates import evaluate_game
from sharp_scout.ncaam.settle import settle_ncaam_ledger
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
FIXTURE_RATINGS = Path(__file__).resolve().parent / "fixtures" / "ncaam" / "torvik_sample.csv"


def _event_with_spread_only_ml_on_soft_book(now: datetime) -> dict:
    """Pinnacle spread only; DraftKings has h2h (must not produce ML candidate)."""
    return {
        "event_id": "ev1",
        "bookmakers": {
            "pinnacle": {
                "last_update": now.isoformat(),
                "markets": {
                    "spreads": [
                        {"side": "home", "price": -110, "point": -3.5},
                        {"side": "away", "price": -110, "point": 3.5},
                    ],
                },
            },
            "draftkings": {
                "last_update": now.isoformat(),
                "markets": {
                    "h2h": [
                        {"side": "home", "price": 150},
                        {"side": "away", "price": -180},
                    ],
                },
            },
        },
    }


def test_ml_skipped_without_pinnacle_h2h_prices(tmp_path, monkeypatch):
    ratings = ratings_mod.load_ratings(FIXTURE_RATINGS)
    now = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
    game = {
        "espn_id": "401",
        "home_team": "Duke",
        "away_team": "North Carolina",
        "commence_time": now + __import__("datetime").timedelta(hours=2),
        "neutral_site": False,
    }
    ev = _event_with_spread_only_ml_on_soft_book(now)
    cands = evaluate_game(game, ev, ratings, now=now)
    assert not any(c["market"] == "h2h" for c in cands)


def test_finalize_closing_lines_accepts_history_path(tmp_path):
    history_path = tmp_path / "line_history.json"
    history_path.write_text(
        json.dumps(
            {
                "ev1|spreads|home": [
                    {"ts": "2026-11-01T20:00:00+00:00", "line": -3.5, "price": -110, "book": "pinnacle"},
                ]
            }
        )
    )
    ledger = {
        "plays": [
            {
                "event_id": "ev1",
                "market": "spreads",
                "side": "home",
                "line": -3.5,
                "price": -110,
                "kickoff": "2026-11-01T21:00:00+00:00",
                "status": "pending",
            }
        ]
    }
    n = finalize_closing_lines(ledger, history_path=history_path, now=datetime(2026, 11, 1, 22, tzinfo=timezone.utc))
    assert n == 1
    assert ledger["plays"][0].get("clv_at")


def test_settle_ncaam_ledger_clv_uses_line_history(tmp_path, monkeypatch):
    hist = tmp_path / "ncaam" / "line_history.json"
    hist.parent.mkdir(parents=True)
    hist.write_text(
        json.dumps(
            {
                "x|spreads|home": [
                    {"ts": "2026-11-01T18:00:00+00:00", "line": -4.0, "price": -110, "book": "pinnacle"},
                ]
            }
        )
    )
    ledger_path = tmp_path / "ncaam_ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "plays": [
                    {
                        "event_id": "x",
                        "market": "spreads",
                        "side": "home",
                        "line": -4.0,
                        "price": -110,
                        "kickoff": "2026-11-01T19:00:00+00:00",
                        "status": "pending",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr("sharp_scout.ncaam.settle.NCAAM_LINE_HISTORY_PATH", hist)
    settle_ncaam_ledger(path=ledger_path, scores=[])
    saved = json.loads(ledger_path.read_text())
    assert saved["plays"][0].get("clv_at")


def test_ensure_daily_ratings_fetches_once_per_et_day(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    fixed = datetime(2026, 11, 2, 12, tzinfo=ET)

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is ET:
                return fixed
            return fixed.astimezone(tz or timezone.utc)

    monkeypatch.setattr(ratings_mod, "datetime", FakeDT)
    old = tmp_path / "ratings_20261101.csv"
    old.write_bytes(FIXTURE_RATINGS.read_bytes())
    latest = tmp_path / "ratings_latest.csv"
    latest.write_bytes(FIXTURE_RATINGS.read_bytes())

    called: list[Path] = []

    def fake_fetch(*, dest: Path | None = None) -> Path:
        dest = dest or ratings_mod.ratings_path_for()
        called.append(dest)
        dest.write_bytes(FIXTURE_RATINGS.read_bytes())
        latest.write_bytes(FIXTURE_RATINGS.read_bytes())
        return dest

    monkeypatch.setattr(ratings_mod, "fetch_torvik_csv", fake_fetch)
    p = ratings_mod.ensure_daily_ratings()
    assert p.name == "ratings_20261102.csv"
    assert called and called[0].name == "ratings_20261102.csv"
    # Second call same ET day should not refetch.
    called.clear()
    p2 = ratings_mod.ensure_daily_ratings()
    assert p2 == p
    assert not called


def test_void_play_without_settled_at_is_never_regraded(tmp_path):
    ledger_path = tmp_path / "ncaam_ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "plays": [
                    {
                        "espn_id": "401921422",
                        "event_id": "401921422",
                        "market": "h2h",
                        "side": "home",
                        "price": 150.0,
                        "units": 0.0,
                        "status": "void",
                        "pnl_units": 0.0,
                    }
                ]
            }
        )
    )
    scores = [{"espn_id": "401921422", "home_score": 80, "away_score": 70}]
    settle_ncaam_ledger(path=ledger_path, scores=scores)
    play = json.loads(ledger_path.read_text())["plays"][0]
    assert play["status"] == "void"
    assert play.get("pnl_units") == 0.0
    assert play.get("units") == 0.0


def test_clv_uses_tip_not_in_game_lines(tmp_path):
    from sharp_scout.ledger.clv import finalize_closing_lines

    kickoff = "2026-11-01T19:00:00+00:00"
    history = {
        "ev1|spreads|home": [
            {"ts": "2026-11-01T18:30:00+00:00", "book": "pinnacle", "line": -3.5, "price": -110},
            {"ts": "2026-11-01T19:30:00+00:00", "book": "pinnacle", "line": -8.0, "price": -110},
        ]
    }
    ledger = {
        "plays": [
            {
                "event_id": "ev1",
                "market": "spreads",
                "side": "home",
                "line": -3.5,
                "price": -110,
                "tip": kickoff,
                "status": "pending",
            }
        ]
    }
    now = datetime(2026, 11, 1, 21, 0, tzinfo=timezone.utc)
    assert finalize_closing_lines(ledger, history=history, now=now) == 1
    assert ledger["plays"][0]["close_line"] == -3.5
    assert ledger["plays"][0]["clv_at"] == "2026-11-01T18:30:00+00:00"


def test_ensure_daily_ratings_falls_back_when_fetch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    fixed = datetime(2026, 11, 3, 8, tzinfo=ET)

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is ET:
                return fixed
            return fixed.astimezone(tz or timezone.utc)

    monkeypatch.setattr(ratings_mod, "datetime", FakeDT)
    latest = tmp_path / "ratings_latest.csv"
    latest.write_bytes(FIXTURE_RATINGS.read_bytes())
    calls: list[int] = []

    def boom(*, dest: Path | None = None) -> Path:
        calls.append(1)
        raise OSError("network down")

    monkeypatch.setattr(ratings_mod, "fetch_torvik_csv", boom)
    assert ratings_mod.ensure_daily_ratings() == latest
    assert len(calls) == 1
    fail_path = tmp_path / "ratings_fetch_failed_20261103.json"
    assert fail_path.is_file()
    assert ratings_mod.ensure_daily_ratings() == latest
    assert len(calls) == 1


def test_ensure_daily_ratings_uses_todays_committed_file_without_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    fixed = datetime(2026, 11, 5, 9, tzinfo=ET)

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is ET:
                return fixed
            return fixed.astimezone(tz or timezone.utc)

    monkeypatch.setattr(ratings_mod, "datetime", FakeDT)
    today = tmp_path / "ratings_20261105.csv"
    today.write_bytes(FIXTURE_RATINGS.read_bytes())

    def boom(*, dest: Path | None = None) -> Path:
        raise AssertionError("fetch should not run when today's cache exists")

    monkeypatch.setattr(ratings_mod, "fetch_torvik_csv", boom)
    assert ratings_mod.ensure_daily_ratings() == today


def test_ensure_daily_ratings_retries_fetch_on_next_et_day_after_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    day1 = datetime(2026, 11, 8, 10, tzinfo=ET)
    day2 = datetime(2026, 11, 9, 10, tzinfo=ET)
    clock = {"now": day1}

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            cur = clock["now"]
            if tz is ET:
                return cur
            return cur.astimezone(tz or timezone.utc)

    monkeypatch.setattr(ratings_mod, "datetime", FakeDT)
    latest = tmp_path / "ratings_latest.csv"
    latest.write_bytes(FIXTURE_RATINGS.read_bytes())
    calls: list[Path] = []

    def fake_fetch(*, dest: Path | None = None) -> Path:
        dest = dest or ratings_mod.ratings_path_for()
        calls.append(dest)
        if len(calls) == 1:
            raise OSError("403 Forbidden")
        dest.write_bytes(FIXTURE_RATINGS.read_bytes())
        return dest

    monkeypatch.setattr(ratings_mod, "fetch_torvik_csv", fake_fetch)
    assert ratings_mod.ensure_daily_ratings() == latest
    assert len(calls) == 1
    assert ratings_mod.ensure_daily_ratings() == latest
    assert len(calls) == 1

    clock["now"] = day2
    got = ratings_mod.ensure_daily_ratings()
    assert got.name == "ratings_20261109.csv"
    assert len(calls) == 2
