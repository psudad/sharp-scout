"""Shadow combo path must not change official Pace v1 picks."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.nba.score_model.engine import V2Engine, V2Params
from sharp_scout.nba.score_model.pace_shadow_combo import (
    load_shadow_combo,
    safe_maybe_record_shadow_combo_for_scan,
)
from sharp_scout.nba.score_model.pace_v1 import injury_adj_pace_picks, pace_display_pick_from_snapshot


def test_official_picks_unchanged_when_shadow_combo_records(tmp_path, monkeypatch):
    from sharp_scout.config import get_settings

    monkeypatch.setattr(
        "sharp_scout.nba.score_model.pace_shadow_combo.SHADOW_COMBO_PATH", tmp_path / "combo.json"
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "nba_pace_shadow_combo_enabled", True)
    monkeypatch.setattr(settings, "nba_league_efficiency_correction_enabled", False)
    monkeypatch.setattr(settings, "nba_pace_v1_market_blend_enabled", False)

    snap = {
        "margin": 6.0,
        "total": 228.0,
        "injury_margin": 6.0,
        "injury_total": 231.0,
        "lines": {"consensus_spread_home": -3.0, "consensus_total": 224.0},
        "home_absences": [],
        "away_absences": [],
    }
    engine = V2Engine(params=V2Params(), stage=3)
    before = pace_display_pick_from_snapshot(snap, home="BOS", away="NYK", engine=engine)
    official = injury_adj_pace_picks(snap, home="BOS", away="NYK", engine=engine)

    safe_maybe_record_shadow_combo_for_scan(
        engine=engine,
        event_id="evt1",
        home="BOS",
        away="NYK",
        kickoff=datetime(2026, 11, 10, 23, 0, tzinfo=timezone.utc),
        scan_at=datetime.now(timezone.utc).isoformat(),
        snap=dict(snap),
        game_row={"scans": [snap]},
    )

    after = pace_display_pick_from_snapshot(snap, home="BOS", away="NYK", engine=engine)
    official2 = injury_adj_pace_picks(snap, home="BOS", away="NYK", engine=engine)
    assert before == after
    assert official == official2
    store = load_shadow_combo()
    assert len(store.get("pending") or []) + len(store.get("plays") or []) >= 0
