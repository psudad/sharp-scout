"""Pre-lock certification filters for the official NCAAM card."""

from __future__ import annotations

from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.qa.model_agreement import model_agreement_and_outlier_reasons


def certification_block_reason(play: dict[str, Any]) -> str | None:
    settings = get_settings()
    if not settings.ncaam_model_agreement_gate_enabled:
        return None
    reasons = model_agreement_and_outlier_reasons(
        play,
        outlier_min_edge=float(settings.ncaam_price_edge_min),
        outlier_price_gap=float(settings.ncaam_one_book_outlier_cents),
    )
    return reasons[0] if reasons else None


def filter_day_picks_for_certification(
    day_picks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return plays allowed on the official card and shadow rows for blocked picks."""
    allowed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for play in day_picks:
        reason = certification_block_reason(play)
        if reason:
            blocked.append({**play, "certification_block": reason})
        else:
            allowed.append(play)
    return allowed, blocked