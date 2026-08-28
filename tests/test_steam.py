"""Steam detection tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sharp_scout.phase4.steam import steam_signal


def _hist(now: datetime, moves: dict[str, tuple[float, float]]) -> dict:
    """Build a history where each book goes from open→close within the window."""
    samples = []
    for book, (first, last) in moves.items():
        samples.append({"ts": (now - timedelta(minutes=60)).isoformat(), "book": book, "line": first, "price": -110})
        samples.append({"ts": (now - timedelta(minutes=5)).isoformat(), "book": book, "line": last, "price": -110})
    return {"e1|spreads|home": samples}


def test_steam_detected_across_multiple_books():
    now = datetime.now(timezone.utc)
    # Three sharp books all move home from -2.5 to -4.0 (toward home).
    hist = _hist(now, {"pinnacle": (-2.5, -4.0), "circa": (-2.5, -4.0), "betonline": (-2.5, -3.5)})
    sig = steam_signal("e1", "spreads", "home", now=now, window_minutes=90, history=hist)
    assert sig["steam"] is True
    assert sig["n_books"] == 3
    assert sig["magnitude"] >= 1.0


def test_no_steam_when_line_flat():
    now = datetime.now(timezone.utc)
    hist = _hist(now, {"pinnacle": (-2.5, -2.5), "circa": (-2.5, -2.5)})
    sig = steam_signal("e1", "spreads", "home", now=now, window_minutes=90, history=hist)
    assert sig["steam"] is False


def test_no_steam_when_move_against_us():
    now = datetime.now(timezone.utc)
    # Line moves away from home (home -2.5 → -1.0), so no steam on home.
    hist = _hist(now, {"pinnacle": (-2.5, -1.0), "circa": (-2.5, -1.0)})
    sig = steam_signal("e1", "spreads", "home", now=now, window_minutes=90, history=hist)
    assert sig["steam"] is False
    assert sig["n_books"] == 0
