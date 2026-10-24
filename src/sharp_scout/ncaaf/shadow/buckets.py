"""EV bucket labels for NCAAF totals shadow ledger."""

from __future__ import annotations

from typing import Any

BUCKET_EV_12_16 = "ev_12_16"
BUCKET_EV_16_PLUS = "ev_16_plus"
BUCKET_CERT_MISS = "cert_miss_4_12"

HIGH_BUCKETS = frozenset({BUCKET_EV_12_16, BUCKET_EV_16_PLUS})


def bucket_for_edge(edge: float | None) -> str | None:
    if edge is None:
        return None
    e = float(edge)
    if e >= 0.16:
        return BUCKET_EV_16_PLUS
    if e >= 0.12:
        return BUCKET_EV_12_16
    return None


def compact_flags(flags: dict[str, Any] | None) -> dict[str, bool]:
    f = flags or {}
    return {
        "rlm": bool(f.get("rlm")),
        "money_split": bool(f.get("money_split")),
        "steam": bool(f.get("steam")),
    }
