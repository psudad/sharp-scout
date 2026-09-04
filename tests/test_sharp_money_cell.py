"""Sharp Money column — flags handle-vs-ticket gaps, greys out noise."""

from __future__ import annotations

import pytest

from sharp_scout.site.build import _sharp_edge_diff_pct, _sharp_money_cell


def _pick(reason: str, *, team: str = "BUF", conf: float | None = None) -> dict:
    return {
        "available": True,
        "stage": "sharp_edge",
        "market": "spread",
        "side": "home",
        "team": team,
        "reason": reason,
        "confidence": conf,
    }


def test_strong_gap_flags_sharp_money_in_caps():
    html = _sharp_money_cell(_pick("+24% money vs tickets on BUF"))
    assert "SHARP MONEY" in html
    assert "sharp-flag strong" in html
    assert "+24%" in html


def test_mild_gap_flags_lowercase_sharp_money():
    html = _sharp_money_cell(_pick("+13% money vs tickets on BUF"))
    assert "sharp-flag mild" in html
    assert "SHARP MONEY" not in html
    assert "+13%" in html


def test_small_gap_is_greyed_out_with_no_flag():
    html = _sharp_money_cell(_pick("+3% money vs tickets on BUF"))
    assert "sharp-flag" not in html
    assert "sharp-money none" in html
    assert "+3%" in html


def test_unavailable_pick_renders_dash():
    assert "—" in _sharp_money_cell({"available": False})
    assert "—" in _sharp_money_cell(None)


def test_diff_recovered_from_confidence_when_reason_unparseable():
    # Legacy cards stored confidence as 0.5 + diff with no percentage in the reason.
    assert _sharp_edge_diff_pct(_pick("sharp edge", conf=0.72)) == pytest.approx(0.22)


def test_non_positive_confidence_diff_is_none():
    assert _sharp_edge_diff_pct({"reason": "sharp edge", "confidence": 0.5}) is None


def test_ncaaf_team_uses_display_code():
    html = _sharp_money_cell(
        _pick("+25% money vs tickets on EASTERN ILLINOIS", team="EASTERN ILLINOIS"),
        sport="ncaaf",
    )
    assert "SHARP MONEY" in html
    assert "EASTERN ILLINOIS" not in html
