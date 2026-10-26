"""NBA props: player must belong to one of the two teams in the event."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.nba.demo import mock_nba_events
from sharp_scout.nba.projections import default_demo_rates
from sharp_scout.nba.props import discover_prop_edges
from sharp_scout.nba.rosters import clear_roster_cache, player_team_for_event


def test_rate_team_blocks_lamelo_on_tor_min():
    clear_roster_cache()
    assert (
        player_team_for_event("LaMelo Ball", home="MIN", away="TOR", rate_team="CHA") is None
    )


def test_lamelo_props_not_scored_on_tor_min():
    rates = default_demo_rates()
    ev = {
        "event_id": "b9f6f078c66480af12ca8bcc44969097",
        "home_team": "MIN",
        "away_team": "TOR",
        "commence_time": "2026-10-25T23:10:00+00:00",
        "bookmakers": mock_nba_events()[0]["bookmakers"],
    }
    edges = discover_prop_edges(ev, rates=rates, file_rate_keys=set(rates.keys()))
    assert not any(e.player_name.lower() == "lamelo ball" for e in edges)


def test_live_shadow_skips_props_when_rate_file_is_stub(tmp_path, monkeypatch):
    from sharp_scout.nba import paths as nba_paths
    from sharp_scout.nba.pipeline import run_nba_shadow

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    rates_path = shadow / "nba_player_rates.json"
    rates_path.write_text(
        '{"players":[{"player_name":"LaMelo Ball","team":"CHA","minutes":32,"pts_per_min":0.7}]}'
    )
    monkeypatch.setattr(nba_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(nba_paths, "NBA_LEDGER_PATH", shadow / "nba_ledger.json")
    monkeypatch.setattr(nba_paths, "NBA_LATEST_SIGNALS_PATH", shadow / "nba_latest_signals.json")
    monkeypatch.setattr(nba_paths, "NBA_LINE_HISTORY_PATH", shadow / "nba_line_history.json")
    monkeypatch.setattr(nba_paths, "NBA_REPORT_PATH", shadow / "nba_paper_report.json")
    monkeypatch.setattr(nba_paths, "NBA_PLAYER_RATES_PATH", rates_path)
    monkeypatch.setattr(nba_paths, "NBA_ARTIFACT_DIR", tmp_path / "artifacts")

    captured: dict = {}

    def fake_fetch(*_a, **_k):
        kick = datetime.now(timezone.utc) + timedelta(hours=12)
        return [
            {
                "event_id": "0123456789abcdef0123456789ab",
                "home_team": "BOS",
                "away_team": "NYK",
                "commence_time": kick,
                "bookmakers": {},
            }
        ]

    def fake_props(*_a, **_k):
        raise AssertionError("fetch_event_props should not run when rate file is thin")

    from sharp_scout.data import odds_api

    monkeypatch.setattr(odds_api.OddsClient, "fetch_odds", fake_fetch)
    monkeypatch.setattr(odds_api.OddsClient, "fetch_event_props", fake_props)
    monkeypatch.setenv("ODDS_API_KEY", "test-key-for-stub")

    payload = run_nba_shadow(demo=False, fetch_props=True, append_ledger=False)
    assert payload["ok"]
    diag = payload.get("prop_diagnostics") or {}
    assert "0123456789abcdef0123456789ab" in (diag.get("props_skipped_thin_rate_file") or [])
