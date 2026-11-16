from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.nba.ledger import append_nba_signals, empty_nba_ledger, save_nba_ledger


def test_append_dedupes_same_side_across_books(tmp_path):
    path = tmp_path / "nba.json"
    save_nba_ledger(empty_nba_ledger(), path)
    kick = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    base = {
        "event_id": "e1",
        "kickoff": kick,
        "away_team": "CHA",
        "home_team": "BOS",
        "market": "spreads",
        "side": "away",
        "line": 1.5,
        "price": -110,
        "units": 1.0,
        "edge": 0.05,
    }
    append_nba_signals([{**base, "book": "fanduel"}], path=path)
    out = append_nba_signals([{**base, "book": "draftkings"}], path=path)
    assert out["added"] == 0
    ledger = path.read_text()
    assert ledger.count("draftkings") + ledger.count("fanduel") == 1