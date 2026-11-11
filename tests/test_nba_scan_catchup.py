"""NBA scan catch-up gate and staleness guard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sharp_scout.nba.schedule_guard import (
    CATCHUP_SCHEDULE_LABEL_ET,
    CRON_CATCHUP,
    ET,
    MAX_CATCHUP_SCANS_PER_DAY,
    catchup_run_allowed,
    is_catchup_cron,
    nba_scan_stale,
    pretip_close_scan_allowed,
    scheduled_cron_run_allowed,
)

# Tue Nov 3, 2026 (EST, UTC-5). First tip 7:00 PM ET.
TIP = datetime(2026, 11, 3, 19, 0, tzinfo=ET).astimezone(timezone.utc)


def _et(h: int, m: int = 0, day: int = 3) -> datetime:
    return datetime(2026, 11, day, h, m, tzinfo=ET).astimezone(timezone.utc)


def test_catchup_cron_in_workflow_and_not_a_slot_cron():
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/nba-shadow.yml").read_text()
    assert f'cron: "{CRON_CATCHUP}"' in wf
    assert is_catchup_cron(CRON_CATCHUP)
    # The slot gate never treats the catch-up line as a primary/backup slot.
    assert not scheduled_cron_run_allowed(CRON_CATCHUP, _et(13, 22), first_tip_utc=TIP)


def test_catchup_runs_when_primary_dropped():
    ok, _ = catchup_run_allowed(_et(13, 52), first_tip_utc=TIP, scan_fresh=False)
    assert ok


def test_catchup_skips_when_fresh():
    ok, why = catchup_run_allowed(_et(13, 52), first_tip_utc=TIP, scan_fresh=True)
    assert not ok and "fresh" in why


def test_catchup_skips_before_primary_slot_and_near_tip():
    assert not catchup_run_allowed(_et(12, 52), first_tip_utc=TIP, scan_fresh=False)[0]
    assert not catchup_run_allowed(_et(13, 22), first_tip_utc=TIP, scan_fresh=False)[0]  # grace
    assert not catchup_run_allowed(_et(18, 52), first_tip_utc=TIP, scan_fresh=False)[0]
    assert catchup_run_allowed(_et(18, 22), first_tip_utc=TIP, scan_fresh=False)[0]


def test_catchup_skips_without_games_and_after_cap():
    assert not catchup_run_allowed(_et(14, 22), first_tip_utc=None, scan_fresh=False)[0]
    ok, why = catchup_run_allowed(
        _et(14, 22), first_tip_utc=TIP, scan_fresh=False, attempts_today=MAX_CATCHUP_SCANS_PER_DAY
    )
    assert not ok and "cap" in why


def test_weekend_catchup_window():
    # Sat Nov 7, 2026: primary 9:07 AM ET, first tip 3:00 PM ET.
    tip = datetime(2026, 11, 7, 15, 0, tzinfo=ET).astimezone(timezone.utc)
    assert catchup_run_allowed(_et(9, 52, day=7), first_tip_utc=tip, scan_fresh=False)[0]
    assert not catchup_run_allowed(_et(9, 22, day=7), first_tip_utc=tip, scan_fresh=False)[0]


def test_staleness_fails_loudly_after_deadline():
    # Weekday deadline = 4:07 PM backup + 45 min = 4:52 PM ET.
    assert not nba_scan_stale(_et(16, 40), first_tip_utc=TIP, scan_fresh=False)[0]
    assert nba_scan_stale(_et(17, 40), first_tip_utc=TIP, scan_fresh=False)[0]
    assert not nba_scan_stale(_et(17, 40), first_tip_utc=TIP, scan_fresh=True)[0]
    assert not nba_scan_stale(_et(17, 40), first_tip_utc=None, scan_fresh=False)[0]
    # Well after the slate has started: stop alarming until tomorrow.
    assert not nba_scan_stale(TIP + timedelta(hours=5), first_tip_utc=TIP, scan_fresh=False)[0]


def test_staleness_deadline_moves_up_for_early_tip():
    early_tip = datetime(2026, 11, 3, 15, 0, tzinfo=ET).astimezone(timezone.utc)
    # Deadline = 2:30 PM ET (30 min before tip), not 4:52 PM.
    assert nba_scan_stale(_et(14, 40), first_tip_utc=early_tip, scan_fresh=False)[0]


def test_pretip_allowed_after_catchup_cap(tmp_path, monkeypatch):
    from sharp_scout.config import get_settings
    from sharp_scout.nba.score_model import paper as paper_mod

    settings = get_settings()
    monkeypatch.setattr(settings, "nba_pace_pre_tip_snapshot_enabled", True)
    store = {
        "games": [
            {
                "kickoff": TIP.isoformat(),
                "scans": [{"at": (TIP - timedelta(hours=4)).isoformat(), "lines": {"consensus_total": 220.0}}],
            }
        ]
    }
    monkeypatch.setattr(paper_mod, "load_paper_store", lambda: store)
    now = TIP - timedelta(minutes=12)
    ok, why = pretip_close_scan_allowed(
        now, first_tip_utc=TIP, attempts_today=MAX_CATCHUP_SCANS_PER_DAY
    )
    assert ok and "cap-exempt" in why
    ok2, why2 = catchup_run_allowed(
        now, first_tip_utc=TIP, scan_fresh=True, attempts_today=MAX_CATCHUP_SCANS_PER_DAY
    )
    assert ok2 and "pre-tip" in why2


def test_pretip_per_game_window_not_first_tip_only(tmp_path, monkeypatch):
    """A 7:40 tip opens at 7:25 ET, not when ESPN's earlier first tip would."""
    from sharp_scout.config import get_settings
    from sharp_scout.nba.score_model import paper as paper_mod

    settings = get_settings()
    monkeypatch.setattr(settings, "nba_pace_pre_tip_snapshot_enabled", True)
    late = datetime(2026, 11, 10, 19, 40, tzinfo=ET).astimezone(timezone.utc)
    espn_first = datetime(2026, 11, 10, 19, 30, tzinfo=ET).astimezone(timezone.utc)
    store = {
        "games": [
            {
                "kickoff": late.isoformat(),
                "scans": [{"at": (late - timedelta(hours=4)).isoformat(), "lines": {"consensus_total": 228.0}}],
            }
        ]
    }
    monkeypatch.setattr(paper_mod, "load_paper_store", lambda: store)
    at_721 = datetime(2026, 11, 10, 19, 21, tzinfo=ET).astimezone(timezone.utc)
    ok_early, why_early = pretip_close_scan_allowed(at_721, first_tip_utc=espn_first)
    assert not ok_early and "no game" in why_early
    at_726 = datetime(2026, 11, 10, 19, 26, tzinfo=ET).astimezone(timezone.utc)
    ok_late, why_late = pretip_close_scan_allowed(at_726, first_tip_utc=espn_first)
    assert ok_late and "19:40" in why_late


def test_catchup_and_pretip_never_touch_official_pace(monkeypatch):
    from sharp_scout.nba.score_model import official_pace as op

    calls: list[int] = []

    def _boom():
        calls.append(1)
        return {"plays": []}

    monkeypatch.setattr(op, "load_official_pace", _boom)
    monkeypatch.setattr(op, "save_official_pace", _boom)
    catchup_run_allowed(_et(14, 22), first_tip_utc=TIP, scan_fresh=False)
    pretip_close_scan_allowed(TIP - timedelta(minutes=10), first_tip_utc=TIP)
    assert calls == []


def test_workflow_commits_shadow_combo_and_extended_catchup_cron():
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/nba-shadow.yml").read_text()
    assert f'cron: "{CRON_CATCHUP}"' in wf
    assert "data/nba_pace_shadow_combo.json" in wf
    assert "12-5" in CRON_CATCHUP
    assert CATCHUP_SCHEDULE_LABEL_ET


def test_pretip_catchup_runs_when_fresh(tmp_path, monkeypatch):
    from sharp_scout.config import get_settings
    from sharp_scout.nba.score_model import paper as paper_mod

    settings = get_settings()
    monkeypatch.setattr(settings, "nba_pace_pre_tip_snapshot_enabled", True)
    monkeypatch.setattr(settings, "nba_pace_pre_tip_snapshot_minutes", 15)
    store = {
        "games": [
            {
                "kickoff": TIP.isoformat(),
                "scans": [
                    {
                        "at": (TIP - timedelta(hours=4)).isoformat(),
                        "lines": {"consensus_total": 220.0},
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(paper_mod, "load_paper_store", lambda: store)
    now = TIP - timedelta(minutes=12)
    ok, why = catchup_run_allowed(now, first_tip_utc=TIP, scan_fresh=True, attempts_today=0)
    assert ok and "pre-tip" in why


def test_scan_fresh_reads_latest_signals(tmp_path, monkeypatch):
    import json

    from sharp_scout.nba import paths as nba_paths
    from sharp_scout.nba import schedule_guard as sg

    p = tmp_path / "nba_latest_signals.json"
    monkeypatch.setattr(nba_paths, "NBA_LATEST_SIGNALS_PATH", p)
    monkeypatch.setattr(sg, "primary_scan_satisfied_for_et_date", lambda d: False)
    p.write_text(json.dumps({"demo": False, "generated_at": "2026-11-03T21:20:55+00:00"}))
    assert sg.scan_fresh_for_et_date(datetime(2026, 11, 3).date())
    assert not sg.scan_fresh_for_et_date(datetime(2026, 11, 4).date())
    p.write_text(json.dumps({"demo": True, "generated_at": "2026-11-03T21:20:55+00:00"}))
    assert not sg.scan_fresh_for_et_date(datetime(2026, 11, 3).date())
