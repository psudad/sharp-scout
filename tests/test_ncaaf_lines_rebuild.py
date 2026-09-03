"""Gameday full-board rebuild gating for NCAAF (drift-proof pregame zone)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.scheduler.ncaaf_lines import (
    REBUILD_LEAD_HOURS,
    rebuild_due,
)


def _plan(kickoff: datetime) -> dict:
    return {
        "games": [
            {
                "event_id": "akron-wake",
                "matchup": "AKRON@WAKE",
                "kickoff": kickoff.isoformat(),
            }
        ],
    }


def test_lead_covers_t3_with_drift_margin():
    # Slightly over 3h so a T-3h window survives cron drift.
    assert REBUILD_LEAD_HOURS >= 3.0


def test_rebuild_at_t3():
    kickoff = datetime(2026, 9, 3, 23, 0, tzinfo=timezone.utc)  # 7pm ET
    now = kickoff - timedelta(hours=3)
    ok, hits = rebuild_due(_plan(kickoff), now=now)
    assert ok is True
    assert len(hits) == 1


def test_rebuild_anywhere_inside_zone_not_just_exact_points():
    # 2h07m out — a drifted cron that missed the exact T-3h point still rebuilds.
    kickoff = datetime(2026, 9, 3, 23, 0, tzinfo=timezone.utc)
    now = kickoff - timedelta(hours=2, minutes=7)
    ok, _ = rebuild_due(_plan(kickoff), now=now)
    assert ok is True


def test_rebuild_at_t1():
    kickoff = datetime(2026, 9, 3, 23, 0, tzinfo=timezone.utc)
    ok, _ = rebuild_due(_plan(kickoff), now=kickoff - timedelta(hours=1))
    assert ok is True


def test_no_rebuild_well_before_zone():
    kickoff = datetime(2026, 9, 3, 23, 0, tzinfo=timezone.utc)
    ok, _ = rebuild_due(_plan(kickoff), now=kickoff - timedelta(hours=6))
    assert ok is False


def test_no_rebuild_after_kickoff():
    kickoff = datetime(2026, 9, 3, 23, 0, tzinfo=timezone.utc)
    ok, _ = rebuild_due(_plan(kickoff), now=kickoff + timedelta(minutes=5))
    assert ok is False


def test_empty_plan_never_rebuilds():
    ok, _ = rebuild_due({"games": []}, now=datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc))
    assert ok is False
