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


def test_timing_settled_shows_game_over():
    html = _play_timing_status_html({"status": "win", "kickoff": "2026-09-01T00:00:00+00:00"})
    assert "Game Over" in html
    assert "WON" in html
    assert "settled-win" in html
    html_loss = _play_timing_status_html({"status": "loss", "kickoff": "2026-09-01T00:00:00+00:00"})
    assert "LOST" in html_loss
    assert "settled-loss" in html_loss


def test_settled_play_shows_final_score():
    play = {
        "status": "win",
        "kickoff": "2026-09-03T00:00:00+00:00",
        "sport": "ncaaf",
        "away_team": "EASTERN ILLINOIS",
        "home_team": "MINNESOTA",
        "away_score": 7,
        "home_score": 59,
    }
    html = _play_timing_status_html(play, sport="ncaaf")
    assert "Game Over — WON" in html
    assert "final-score" in html
    assert "7" in html and "59" in html
    assert "Final" in html


def test_settled_play_without_scores_omits_final_line():
    html = _play_timing_status_html({"status": "loss", "kickoff": "2026-09-03T00:00:00+00:00"})
    assert "Game Over — LOST" in html
    assert "final-score" not in html
