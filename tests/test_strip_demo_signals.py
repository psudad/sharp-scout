"""Demo/seed games (e.g. ALA@UGA) must never leak onto the live site."""

from __future__ import annotations

from sharp_scout.site.build import _strip_demo_signals


def test_strips_demo_event_ids_across_collections():
    sig = {
        "demo": True,
        "n_games": 1,
        "games": [{"event_id": "demo-ala-uga", "home_team": "UGA", "away_team": "ALA"}],
        "plays": [{"event_id": "demo-ala-uga"}],
        "stage_picks": [{"event_id": "demo-ala-uga", "market": "spread"}],
        "signals": [{"event_id": "demo-ala-uga"}],
        "split_boards": [{"event_id": "demo-ala-uga"}],
        "ratings": [{"team": "UGA", "power": 1.0}],
    }
    out = _strip_demo_signals(sig)
    for key in ("games", "plays", "stage_picks", "signals", "split_boards"):
        assert out[key] == [], key
    assert out["n_games"] == 0
    assert out["ratings"] == []


def test_keeps_real_games_and_drops_only_demo():
    sig = {
        "games": [
            {"event_id": "demo-ala-uga", "home_team": "UGA", "away_team": "ALA"},
            {"event_id": "real-123", "home_team": "OSU", "away_team": "MICH"},
        ],
        "stage_picks": [
            {"event_id": "demo-ala-uga"},
            {"event_id": "real-123"},
        ],
    }
    out = _strip_demo_signals(sig)
    assert [g["event_id"] for g in out["games"]] == ["real-123"]
    assert [s["event_id"] for s in out["stage_picks"]] == ["real-123"]
    assert out["n_games"] == 1


def test_empty_signals_unchanged():
    assert _strip_demo_signals({}) == {}
