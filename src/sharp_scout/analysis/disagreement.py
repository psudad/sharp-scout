"""The "Why is our model wrong?" engine.

Every time Sharp Scout disagrees materially with the market (``|p_true - p_mkt|`` above a
threshold), we record a structured *disagreement* and auto-classify the most likely cause.
Over a season this reveals which kinds of disagreement are real edges vs. the model being
naive — the evidence needed to decide whether the matchup-interaction engine is worth
trusting.

Categories (from Tom's spec):
    injury, qb, weather, matchup, scheme, market_overreaction, public_bias,
    model_deficiency, sample_size, usage_change, coaching_change, unknown

Auto-tagging is deliberately conservative: it uses only signals we actually have at pick
time (weather, QB backup flags, Action Network split flags). Everything else defaults to
``unknown`` and can be overridden manually via ``category_manual``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sharp_scout.config import get_settings

logger = logging.getLogger(__name__)

CATEGORIES = (
    "injury",
    "qb",
    "weather",
    "matchup",
    "scheme",
    "market_overreaction",
    "public_bias",
    "model_deficiency",
    "sample_size",
    "usage_change",
    "coaching_change",
    "unknown",
)


def classify_disagreement(
    play: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return {category, confidence, evidence} for a single model-vs-market disagreement."""
    context = context or {}
    flags = play.get("flags") or {}
    evidence: list[str] = []

    p_true = play.get("p_true")
    p_mkt = play.get("p_mkt")
    magnitude = abs((p_true or 0) - (p_mkt or 0)) if p_true is not None and p_mkt is not None else None
    if magnitude is not None:
        evidence.append(f"|p_true-p_mkt|={magnitude:.3f}")

    category = "unknown"
    confidence = 0.3

    # Weather (only if a wind figure is supplied on the play/context)
    wind = play.get("wind") if play.get("wind") is not None else context.get("wind")
    if wind is not None:
        try:
            if float(wind) >= 15:
                category = "weather"
                confidence = 0.6
                evidence.append(f"wind={float(wind):.0f}mph ≥ 15")
        except (TypeError, ValueError):
            pass

    # QB downgrade/upgrade
    if category == "unknown" and (play.get("qb_backup") or context.get("qb_backup")):
        category = "qb"
        confidence = 0.6
        evidence.append("backup QB flag set")

    # Injury (inactive skill players configured)
    if category == "unknown":
        inactive = get_settings().inactive_list
        if inactive:
            category = "injury"
            confidence = 0.4
            evidence.append(f"{len(inactive)} inactive player(s) configured")

    # Market structure: reverse line movement toward us → public was mispricing
    if category == "unknown" and flags.get("rlm"):
        category = "public_bias"
        confidence = 0.55
        evidence.append("RLM toward our side (line moved against public)")

    # Sharp money on our side vs public tickets → market overreaction the sharps faded
    if category == "unknown" and flags.get("money_split"):
        category = "market_overreaction"
        confidence = 0.5
        evidence.append("sharp money on our side vs public tickets")

    # Large disagreement with no confirming market structure → likely model deficiency
    if category == "unknown" and magnitude is not None and magnitude >= 0.10:
        category = "model_deficiency"
        confidence = 0.35
        evidence.append("large edge, no market confirmation")

    return {
        "category": category,
        "confidence": round(confidence, 2),
        "evidence": evidence,
        "magnitude": round(magnitude, 4) if magnitude is not None else None,
    }


def build_disagreements(
    signals: list[dict[str, Any]],
    *,
    threshold: float | None = None,
    season: int | None = None,
    week: int | None = None,
) -> list[dict[str, Any]]:
    """Create disagreement records for signals whose model/market gap clears the threshold."""
    thr = get_settings().disagreement_prob_threshold if threshold is None else threshold
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for s in signals:
        p_true = s.get("p_true")
        p_mkt = s.get("p_mkt")
        if p_true is None or p_mkt is None:
            continue
        if abs(p_true - p_mkt) < thr:
            continue
        cls = classify_disagreement(s)
        out.append(
            {
                "id": str(uuid.uuid4())[:8],
                "created_at": now,
                "season": season,
                "week": week,
                "event_id": s.get("event_id"),
                "away_team": s.get("away_team"),
                "home_team": s.get("home_team"),
                "market": s.get("market"),
                "side": s.get("side"),
                "line": s.get("line"),
                "book": s.get("book"),
                "p_true": p_true,
                "p_mkt": p_mkt,
                "edge": s.get("edge"),
                "tier": s.get("tier"),
                "direction": "model_higher" if p_true > p_mkt else "model_lower",
                "category": cls["category"],
                "category_manual": None,
                "confidence": cls["confidence"],
                "evidence": cls["evidence"],
                "magnitude": cls["magnitude"],
                # filled after settlement to learn which categories are real edges
                "outcome": None,
            }
        )
    return out


def resolve_category(record: dict[str, Any]) -> str:
    return record.get("category_manual") or record.get("category") or "unknown"


def summarize_disagreements(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-category counts and (once settled) hit rate — which disagreements pay off."""
    by_cat: dict[str, dict[str, Any]] = {}
    for r in records:
        cat = resolve_category(r)
        b = by_cat.setdefault(cat, {"count": 0, "wins": 0, "losses": 0, "pushes": 0})
        b["count"] += 1
        outcome = r.get("outcome")
        if outcome == "win":
            b["wins"] += 1
        elif outcome == "loss":
            b["losses"] += 1
        elif outcome == "push":
            b["pushes"] += 1
    for cat, b in by_cat.items():
        decided = b["wins"] + b["losses"]
        b["win_pct"] = round(b["wins"] / decided, 3) if decided else None
        b["record"] = f"{b['wins']}-{b['losses']}" + (f"-{b['pushes']}" if b["pushes"] else "")
    return {
        "n": len(records),
        "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1]["count"])),
    }
