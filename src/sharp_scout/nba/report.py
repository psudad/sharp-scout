"""Paper-trading pass/fail report (CLV + calibration) for NBA shadow mode."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.nba.clv import summarize_nba_clv


def _parse_day(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def in_paper_window(when: date | None = None) -> bool:
    settings = get_settings()
    when = when or datetime.now(timezone.utc).date()
    start = _parse_day(settings.nba_paper_start)
    end = _parse_day(settings.nba_paper_end)
    return start <= when <= end


def calibration_buckets(plays: list[dict[str, Any]], *, bins: int = 5) -> list[dict[str, Any]]:
    scored = [p for p in plays if p.get("p_true") is not None and p.get("status") in ("win", "loss")]
    if not scored:
        return []
    scored.sort(key=lambda p: float(p["p_true"]))
    chunk = max(1, len(scored) // bins)
    out = []
    for i in range(0, len(scored), chunk):
        part = scored[i : i + chunk]
        if not part:
            continue
        avg_p = sum(float(p["p_true"]) for p in part) / len(part)
        wins = sum(1 for p in part if p.get("status") == "win")
        out.append(
            {
                "n": len(part),
                "avg_p_true": round(avg_p, 4),
                "win_rate": round(wins / len(part), 4),
            }
        )
    return out


def pass_fail_for_type(plays: list[dict[str, Any]], *, kind: str) -> dict[str, Any]:
    subset = [p for p in plays if _kind(p) == kind and p.get("clv_prob") is not None]
    if len(subset) < 5:
        return {"kind": kind, "status": "insufficient_data", "n": len(subset)}
    beat = sum(1 for p in subset if float(p["clv_prob"]) > 0)
    avg_clv = sum(float(p["clv_prob"]) for p in subset) / len(subset)
    # Pass: beat close >= 52% and mean CLV >= 0
    passed = (beat / len(subset)) >= 0.52 and avg_clv >= 0.0
    return {
        "kind": kind,
        "status": "pass" if passed else "fail",
        "n": len(subset),
        "beat_close_pct": round(beat / len(subset), 4),
        "avg_clv_prob": round(avg_clv, 4),
    }


def _kind(play: dict[str, Any]) -> str:
    if play.get("play_type") == "prop":
        return f"prop:{play.get('market')}"
    return f"game:{play.get('market')}"


def build_paper_report(ledger: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    plays = ledger.get("plays") or []
    kinds = sorted({_kind(p) for p in plays})
    model_filter: dict[str, Any] = {}
    score_model_paper: dict[str, Any] = {}
    try:
        from sharp_scout.nba.score_model.model_filter import summarize_model_filter
        from sharp_scout.nba.score_model.paper import load_paper_store, summarize_score_paper

        model_filter = summarize_model_filter(ledger)
        score_model_paper = summarize_score_paper(load_paper_store())
    except Exception:  # noqa: BLE001
        pass
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_window": {"start": settings.nba_paper_start, "end": settings.nba_paper_end},
        "in_window": in_paper_window(),
        "clv_summary": summarize_nba_clv(ledger),
        "calibration": calibration_buckets(plays),
        "pass_fail": [pass_fail_for_type(plays, kind=k) for k in kinds],
        "n_plays": len(plays),
        "model_filter": model_filter,
        "score_model_paper": score_model_paper,
    }


def write_paper_report(ledger: dict[str, Any], path: Any) -> dict[str, Any]:
    report = build_paper_report(ledger)
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report
