"""True close line selection from paper scans."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.nba.score_model.true_close import game_missing_true_close_scan, select_true_close_scan


def test_select_last_scan_in_pretip_window():
    kick = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
    scans = [
        {"at": (kick - timedelta(hours=3)).isoformat(), "lines": {"consensus_total": 221.0}},
        {
            "at": (kick - timedelta(minutes=10)).isoformat(),
            "lines": {"consensus_total": 223.5, "consensus_spread_home": -4.5},
        },
        {"at": (kick + timedelta(minutes=2)).isoformat(), "lines": {"consensus_total": 224.0}},
    ]
    snap, cap = select_true_close_scan(scans, kick)
    assert cap is not None
    assert snap is not None
    assert snap["lines"]["consensus_total"] == 224.0


def test_game_missing_true_close_through_post_tip_window(monkeypatch):
    from sharp_scout.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "nba_pace_pre_tip_snapshot_minutes", 15)
    monkeypatch.setattr(settings, "nba_pace_true_close_post_minutes", 5)
    kick = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
    g = {
        "kickoff": kick.isoformat(),
        "scans": [{"at": (kick - timedelta(hours=3)).isoformat(), "lines": {"consensus_total": 220.0}}],
    }
    assert not game_missing_true_close_scan(g, now=kick - timedelta(minutes=20))
    assert game_missing_true_close_scan(g, now=kick + timedelta(minutes=2))
    g["scans"].append(
        {
            "at": (kick - timedelta(minutes=3)).isoformat(),
            "lines": {"consensus_total": 223.0, "consensus_spread_home": -2.0},
        }
    )
    assert not game_missing_true_close_scan(g, now=kick + timedelta(minutes=2))
