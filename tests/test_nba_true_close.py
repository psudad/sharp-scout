"""True close line selection from paper scans."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.nba.score_model.true_close import select_true_close_scan


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
