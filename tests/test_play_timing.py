"""When-to-bet guidance for open Sharp Plays."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.site.build import _play_timing_status_html


def _play(kickoff: datetime) -> dict:
    return {"status": "pending", "kickoff": kickoff.isoformat()}


def test_timing_hold_far_from_kickoff():
    kick = datetime.now(timezone.utc) + timedelta(hours=48)
    html = _play_timing_status_html(_play(kick))
    assert "Don't play yet" in html
    assert "lock in closer to game time" in html


def test_timing_watch_between_12_and_3_hours():
    kick = datetime.now(timezone.utc) + timedelta(hours=8)
    html = _play_timing_status_html(_play(kick))
    assert "T-3h" in html


def test_timing_soon_between_3_and_1_hours():
    kick = datetime.now(timezone.utc) + timedelta(hours=2)
    html = _play_timing_status_html(_play(kick))
    assert "T-1h" in html


def test_timing_lock_within_one_hour():
    kick = datetime.now(timezone.utc) + timedelta(minutes=45)
    html = _play_timing_status_html(_play(kick))
    assert "Lock in now" in html


def test_timing_settled_uses_badge():
    html = _play_timing_status_html({"status": "win", "kickoff": "2026-09-01T00:00:00+00:00"})
    assert "WIN" in html
