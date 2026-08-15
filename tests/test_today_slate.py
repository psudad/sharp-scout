"""Tests for today's slate event resolution."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_today_slate import _resolve_today_events, _today_window_et  # noqa: E402


def test_resolve_today_events_uses_preseason_when_regular_empty(tmp_path):
    start_utc, end_utc, splits_date = _today_window_et("20260815")
    kickoff = datetime(2026, 8, 15, 17, 0, tzinfo=timezone.utc)
    preseason_event = {
        "event_id": "pre-car-buf",
        "commence_time": kickoff,
        "home_team": "BUF",
        "away_team": "CAR",
        "bookmakers": {},
    }

    client = MagicMock()
    client.fetch_odds.side_effect = lambda sport=None: (
        [] if sport == "americanfootball_nfl"
        else [preseason_event]
    )
    client.fetch_events.return_value = []

    events, source = _resolve_today_events(client, start_utc, end_utc, splits_date)
    assert source == "odds_api_preseason"
    assert len(events) == 1
    assert events[0]["away_team"] == "CAR"


def test_resolve_today_events_falls_back_to_manual_slate(tmp_path, monkeypatch):
    from sharp_scout.config import DATA_DIR

    start_utc, end_utc, splits_date = _today_window_et("20260815")
    slate_dir = DATA_DIR / "slates"
    slate_dir.mkdir(parents=True, exist_ok=True)
    slate_path = slate_dir / f"{splits_date}.json"
    kickoff = datetime(2026, 8, 15, 20, 0, tzinfo=timezone.utc)
    slate_path.write_text(
        """
        {
          "date": "20260815",
          "games": [
            {
              "event_id": "manual-jax-no",
              "home_team": "NO",
              "away_team": "JAX",
              "commence_time": "2026-08-15T20:00:00+00:00",
              "bookmakers": {
                "draftkings": {
                  "title": "DraftKings",
                  "markets": {
                    "spreads": [
                      {"side": "away", "price": -110, "point": -3},
                      {"side": "home", "price": -110, "point": 3}
                    ]
                  }
                }
              }
            }
          ]
        }
        """
    )

    client = MagicMock()
    client.fetch_odds.return_value = []
    client.fetch_events.return_value = []

    events, source = _resolve_today_events(client, start_utc, end_utc, splits_date)
    assert source == f"manual_slate:{splits_date}.json"
    assert len(events) == 1
    assert events[0]["away_team"] == "JAX"

    slate_path.unlink()
