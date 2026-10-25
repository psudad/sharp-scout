"""Score engine bootstrap: priors, event keys, incremental fetch hooks."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.nba.score_model.engine import V2Engine, V2Params
from sharp_scout.nba.score_model.state import (
    _game_key,
    apply_committed_priors,
    load_committed_priors,
)


def test_game_key_uses_event_id():
    g = {
        "event_id": "401810001",
        "away": "NYK",
        "home": "BOS",
        "date": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    assert _game_key(g) == "eid:401810001"


def test_apply_committed_priors_loads_teams(tmp_path, monkeypatch):
    priors = {
        "version": 1,
        "for_season": "2026-27",
        "teams": {
            "BOS": {"off": 118.0, "def": 108.0, "pace": 98.5},
            "NYK": {"off": 112.0, "def": 111.0, "pace": 99.0},
        },
    }
    path = tmp_path / "priors.json"
    path.write_text(__import__("json").dumps(priors))
    monkeypatch.setattr("sharp_scout.nba.score_model.state.PRIORS_PATH", path)
    raw = load_committed_priors(path)
    engine = V2Engine(params=V2Params(), stage=3)
    apply_committed_priors(engine, raw)
    assert engine.team_off.get("BOS") == 118.0
    proj = engine.project("BOS", "NYK", game_date=datetime.now(timezone.utc))
    assert 200 < proj["total"] < 250


def test_finals_by_event_dedupe(monkeypatch):
    from sharp_scout.data import espn_nba

    rows = [
        {"event_id": "1", "away_team": "NYK", "home_team": "BOS", "kickoff": "2026-01-01"},
        {"event_id": "2", "away_team": "NYK", "home_team": "BOS", "kickoff": "2026-02-01"},
    ]

    def fake_board(params):
        return rows

    monkeypatch.setattr(espn_nba, "_fetch_scoreboard", fake_board)
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    until = datetime(2026, 2, 2, tzinfo=timezone.utc)
    out = espn_nba.fetch_espn_nba_finals_by_event(since=since, until=until)
    assert len(out) == 2
