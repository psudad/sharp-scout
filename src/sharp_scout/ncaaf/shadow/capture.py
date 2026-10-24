"""Extract NCAAF totals candidates for private high-EV shadow tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.copy.explain import collapse_best_signals
from sharp_scout.ncaaf.shadow.buckets import (
    BUCKET_CERT_MISS,
    BUCKET_EV_12_16,
    BUCKET_EV_16_PLUS,
    bucket_for_edge,
)
from sharp_scout.ncaaf.shadow.ledger import upsert_signals
from sharp_scout.qa.product_gate import evaluate_product_play

logger = logging.getLogger(__name__)

_EV_FLOOR_PREFIX = "EV "
_CERT_MISS_ALLOWED_FRAGMENTS = (
    "Pinnacle no-vig",
    "no Pinnacle",
    "sharp no-vig",
    "missing sharp fair",
    "money",
    "split-board",
    "split board",
    "book(s) on line",
    "price ",
    "until kickoff",
    "total sharp",
    "spread sharp",
    "confirmation",
    "no_pinnacle",
)


def _reason_blocks_cert_miss(reason: str) -> bool:
    r = reason.lower()
    if "model-tilt" in r or "product ceiling" in r:
        return True
    if reason.startswith(_EV_FLOOR_PREFIX) and "<" in reason and "floor" in reason:
        return True
    if reason.startswith("outside narrow"):
        return True
    if reason.startswith("tier="):
        return True
    if reason.startswith("market ") and "not in product" in reason:
        return True
    if reason.startswith("shadow market"):
        return True
    return False


def _cert_miss_only_reasons(reasons: tuple[str, ...] | list[str]) -> bool:
    if not reasons:
        return False
    for reason in reasons:
        if _reason_blocks_cert_miss(reason):
            return False
        if not any(frag.lower() in reason.lower() for frag in _CERT_MISS_ALLOWED_FRAGMENTS):
            return False
    return True


def _is_cert_miss_candidate(play: dict[str, Any], *, signals: dict[str, Any]) -> bool:
    edge = play.get("edge")
    if edge is None:
        return False
    e = float(edge)
    if e < 0.04 or e >= 0.12:
        return False
    if not play.get("filter_passed"):
        return False
    if str(play.get("market") or "") != "totals":
        return False
    res = evaluate_product_play(play, signals=signals, sport="ncaaf")
    if res.ok:
        return False
    return _cert_miss_only_reasons(res.reasons)


def _totals_signals(all_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in all_signals if str(s.get("market") or "") == "totals"]


def record_from_pipeline(
    all_signals: list[dict[str, Any]],
    *,
    signals_payload: dict[str, Any] | None = None,
    season: int | None = None,
    week: int | None = None,
) -> dict[str, Any]:
    """Persist shadow rows from an in-memory NCAAF pipeline run (zero extra API calls)."""
    settings = get_settings()
    if not settings.ncaaf_totals_shadow_enabled:
        return {"ok": False, "reason": "disabled"}

    payload = signals_payload or {}
    captured_at = payload.get("generated_at") or datetime.now(timezone.utc).isoformat()
    totals = _totals_signals(all_signals)
    collapsed = collapse_best_signals(totals, only_passed=False)

    high_12_16: list[dict[str, Any]] = []
    high_16_plus: list[dict[str, Any]] = []
    cert_miss: list[dict[str, Any]] = []

    for s in collapsed:
        edge = s.get("edge")
        if edge is None:
            continue
        b = bucket_for_edge(float(edge))
        if b == BUCKET_EV_12_16:
            high_12_16.append(s)
        elif b == BUCKET_EV_16_PLUS:
            high_16_plus.append(s)
        elif _is_cert_miss_candidate(s, signals=payload):
            cert_miss.append(s)

    r1 = upsert_signals(high_12_16, bucket=BUCKET_EV_12_16, captured_at=captured_at, season=season, week=week)
    r2 = upsert_signals(high_16_plus, bucket=BUCKET_EV_16_PLUS, captured_at=captured_at, season=season, week=week)
    r3 = upsert_signals(cert_miss, bucket=BUCKET_CERT_MISS, captured_at=captured_at, season=season, week=week)

    result = {
        "ok": True,
        "captured_at": captured_at,
        "n_high_12_16": len(high_12_16),
        "n_high_16_plus": len(high_16_plus),
        "n_cert_miss": len(cert_miss),
        "ledger": {
            "ev_12_16": r1,
            "ev_16_plus": r2,
            "cert_miss": r3,
        },
    }
    logger.info(
        "NCAAF totals shadow: high_12_16=%d high_16+=%d cert_miss=%d (added %d/%d/%d)",
        len(high_12_16),
        len(high_16_plus),
        len(cert_miss),
        r1["added"],
        r2["added"],
        r3["added"],
    )
    return result
