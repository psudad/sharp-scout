"""Manual NBA game lines (fallback when Jason hand-enters FanDuel quotes)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sharp_scout.nba.manual_lines import (
    manual_lines_for_current_slate,
    manual_lines_page_note,
    manual_lines_slate_date_et,
)
from sharp_scout.utils.slate import ET


def test_manual_lines_slate_date_from_field():
    doc = {"slate_date_et": "2026-10-29", "games": [{"away": "A", "home": "B"}]}
    assert manual_lines_slate_date_et(doc) == date(2026, 10, 29)


def test_manual_lines_only_active_on_matching_et_slate():
    doc = {
        "slate_date_et": "2026-10-28",
        "as_of_et": "6:20 PM ET Oct 28, 2026",
        "games": [{"away": "GSW", "home": "MIN", "total": 227.5}],
    }
    oct29 = datetime(2026, 10, 29, 16, 0, tzinfo=ET).astimezone(timezone.utc)
    assert manual_lines_for_current_slate(doc, now=oct29) is False
    assert manual_lines_page_note(doc, now=oct29) == ""
    oct28 = datetime(2026, 10, 28, 16, 0, tzinfo=ET).astimezone(timezone.utc)
    assert manual_lines_for_current_slate(doc, now=oct28) is True
    note = manual_lines_page_note(doc, now=oct28)
    assert "manual entry" in note
    assert "paused" not in note.lower()
    assert "Odds API" not in note
