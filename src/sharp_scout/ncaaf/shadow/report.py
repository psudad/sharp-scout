"""Summary stats for NCAAF high-EV totals shadow ledger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sharp_scout.ncaaf.shadow import paths
from sharp_scout.ncaaf.shadow.buckets import BUCKET_CERT_MISS, BUCKET_EV_12_16, BUCKET_EV_16_PLUS, HIGH_BUCKETS
from sharp_scout.ncaaf.shadow.ledger import load_ledger


def _record_stats(plays: list[dict[str, Any]]) -> dict[str, Any]:
    wins = losses = pushes = pending = 0
    units = 0.0
    clv_probs: list[float] = []
    for p in plays:
        st = p.get("status") or "pending"
        if st == "win":
            wins += 1
        elif st == "loss":
            losses += 1
        elif st == "push":
            pushes += 1
        else:
            pending += 1
        if p.get("pnl_units") is not None:
            units += float(p["pnl_units"])
        if p.get("clv_prob") is not None:
            clv_probs.append(float(p["clv_prob"]))
    decided = wins + losses + pushes
    roi = (units / decided) if decided else None
    avg_clv = (sum(clv_probs) / len(clv_probs)) if clv_probs else None
    return {
        "n": len(plays),
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "pending": pending,
        "units": round(units, 2),
        "roi_per_play": round(roi, 4) if roi is not None else None,
        "avg_clv_prob": round(avg_clv, 4) if avg_clv is not None else None,
        "n_clv": len(clv_probs),
    }


def build_summary(ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger = ledger or load_ledger()
    plays = ledger.get("plays") or []
    by_bucket: dict[str, list[dict[str, Any]]] = {
        BUCKET_EV_12_16: [],
        BUCKET_EV_16_PLUS: [],
        BUCKET_CERT_MISS: [],
    }
    for p in plays:
        b = p.get("bucket")
        if b in by_bucket:
            by_bucket[b].append(p)

    by_side_bucket: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for b, rows in by_bucket.items():
        by_side_bucket[b] = {"over": [], "under": []}
        for p in rows:
            side = str(p.get("side") or "").lower()
            if side in by_side_bucket[b]:
                by_side_bucket[b][side].append(p)

    high_only = [p for p in plays if p.get("bucket") in HIGH_BUCKETS]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sport": "ncaaf",
        "market": "totals",
        "mode": "shadow_high_ev",
        "overall_high_ev": _record_stats(high_only),
        "by_bucket": {b: _record_stats(rows) for b, rows in by_bucket.items()},
        "by_bucket_side": {
            b: {side: _record_stats(rows) for side, rows in sides.items()}
            for b, sides in by_side_bucket.items()
        },
        "n_plays_total": len(plays),
    }


def write_summary_and_report(*, ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = build_summary(ledger)
    paths.SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    paths.SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    paths.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    paths.MARKDOWN_REPORT_PATH.write_text(_markdown_report(summary) + "\n")
    return summary


def _markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# NCAAF totals — high-EV shadow paper track",
        "",
        "Private paper ledger for totals candidates above the LOCKED card EV ceiling (12%). "
        "Not linked from the public GitHub Pages board.",
        "",
        f"_Generated: {summary.get('generated_at')}_",
        "",
        "## High-EV buckets combined (12%+)",
        "",
    ]
    ov = summary.get("overall_high_ev") or {}
    lines.append(
        f"- **Record:** {ov.get('record', '—')} ({ov.get('pending', 0)} pending)  "
        f"**Units:** {ov.get('units', 0)}  **ROI/play:** {ov.get('roi_per_play', '—')}  "
        f"**Avg CLV:** {ov.get('avg_clv_prob', '—')}"
    )
    lines.extend(["", "## By bucket", ""])
    for label, key in (
        ("12% – <16%", BUCKET_EV_12_16),
        ("16%+", BUCKET_EV_16_PLUS),
        ("4–12% cert miss (p_fair / confirmation only)", BUCKET_CERT_MISS),
    ):
        st = (summary.get("by_bucket") or {}).get(key) or {}
        lines.append(
            f"### {label}\n"
            f"- Record {st.get('record', '—')} | units {st.get('units', 0)} | "
            f"ROI/play {st.get('roi_per_play', '—')} | avg CLV {st.get('avg_clv_prob', '—')}"
        )
        side_stats = (summary.get("by_bucket_side") or {}).get(key) or {}
        for side in ("over", "under"):
            ss = side_stats.get(side) or {}
            lines.append(
                f"  - **{side.title()}:** {ss.get('record', '—')} "
                f"({ss.get('n', 0)} rows, avg CLV {ss.get('avg_clv_prob', '—')})"
            )
        lines.append("")
    return "\n".join(lines)
