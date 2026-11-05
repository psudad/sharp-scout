"""Shared test defaults."""

import pytest


@pytest.fixture(autouse=True)
def _legacy_product_gate(request, monkeypatch):
    """Legacy gate tests use DraftKings fixtures without Pinnacle fair; the Nov 2026
    high-confidence rules are covered in test_hc_rules.py (marker: hc_rules)."""
    from sharp_scout.config import get_settings

    if request.node.get_closest_marker("hc_rules") is None:
        monkeypatch.setenv("PRODUCT_HC_RULES_ENABLED", "false")
        monkeypatch.setenv("PRO_TIER_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
