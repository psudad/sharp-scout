"""Shared kickoff helpers and shadow ledger guards."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.ncaaf.shadow.ledger import flag_logged_after_kickoff, upsert_signals
from sharp_scout.ncaaf.shadow import paths as shadow_paths
from sharp_scout.utils.kickoff import kickoff_still_future, logged_at_or_after_kickoff


def test_kickoff_still_future():
    now = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
    assert kickoff_still_future({"kickoff": "2026-10-24T20:00:00+00:00"}, now=now)
    assert not kickoff_still_future({"kickoff": "2026-10-24T19:00:00+00:00"}, now=now)


def test_logged_at_or_after_kickoff():
    row = {"kickoff": "2026-10-24T20:00:00+00:00", "first_seen_at": "2026-10-24T20:05:00+00:00"}
    assert logged_at_or_after_kickoff(row)


def test_shadow_upsert_skips_post_kickoff_new_row(tmp_path, monkeypatch):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(shadow_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(shadow_paths, "LEDGER_PATH", shadow / "ledger.json")

    signal = {
        "event_id": "late",
        "away_team": "A",
        "home_team": "B",
        "kickoff": "2026-10-24T18:00:00+00:00",
        "market": "totals",
        "side": "over",
        "line": 50.5,
        "book": "dk",
        "price": -110,
        "edge": 0.15,
    }
    result = upsert_signals([signal], bucket="ev_12_16", captured_at="2026-10-24T19:00:00+00:00")
    assert result["added"] == 0
    assert result["skipped_past_kickoff"] == 1


def test_flag_logged_after_kickoff_marks_existing():
    ledger = {
        "plays": [
            {
                "kickoff": "2026-10-24T20:00:00+00:00",
                "first_seen_at": "2026-10-24T20:10:00+00:00",
            }
        ]
    }
    assert flag_logged_after_kickoff(ledger) == 1
    assert ledger["plays"][0]["integrity_flags"]["logged_after_kickoff"] is True
