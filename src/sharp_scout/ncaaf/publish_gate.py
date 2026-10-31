"""Gate NCAAF GitHub Pages / docs publishing (model QA thresholds unchanged)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from sharp_scout.qa.gate import MIN_RATED_TEAMS_NCAAF, QAGateResult, review_signals

logger = logging.getLogger(__name__)


def demo_run_allowed() -> bool:
    """Explicit opt-in for local demo / skip-pbp runs (does not enable docs publish)."""
    return os.environ.get("SHARP_SCOUT_DEMO", "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class NcaafPublishDecision:
    publishable: bool
    reason: str
    n_rated_teams: int
    skip_pbp: bool
    threshold: int = MIN_RATED_TEAMS_NCAAF


def decide_ncaaf_publish(
    payload: dict[str, Any],
    *,
    skip_pbp: bool = False,
    qa_result: QAGateResult | None = None,
) -> NcaafPublishDecision:
    """Return whether this pipeline payload may be written to committed docs/."""
    n_teams = len(payload.get("ratings") or [])
    threshold = MIN_RATED_TEAMS_NCAAF

    if payload.get("demo"):
        return NcaafPublishDecision(False, "demo_mode", n_teams, skip_pbp)

    if skip_pbp:
        return NcaafPublishDecision(False, "skip_pbp", n_teams, skip_pbp)

    if n_teams < threshold:
        return NcaafPublishDecision(
            False,
            f"rated_teams_{n_teams}_below_{threshold}",
            n_teams,
            skip_pbp,
        )

    if qa_result is not None:
        if qa_result.block_deploy:
            return NcaafPublishDecision(False, "qa_layer1", n_teams, skip_pbp)
    else:
        layer1 = review_signals(payload, sport="ncaaf", allow_demo=False)
        if any(i.severity == "block" for i in layer1):
            return NcaafPublishDecision(False, "qa_layer1", n_teams, skip_pbp)

    return NcaafPublishDecision(True, "ok", n_teams, skip_pbp)


def may_append_ncaaf_ledger(
    payload: dict[str, Any],
    *,
    skip_pbp: bool = False,
    demo: bool = False,
) -> bool:
    """Ledger locks / paper rows require the same provenance as a public board publish."""
    if demo or payload.get("demo"):
        return False
    if skip_pbp:
        return False
    layer1 = review_signals(payload, sport="ncaaf", allow_demo=False)
    return not any(i.severity == "block" for i in layer1)


def stamp_publishable(payload: dict[str, Any], decision: NcaafPublishDecision) -> None:
    payload["publishable"] = decision.publishable
    if not decision.publishable:
        payload["publish_block_reason"] = decision.reason
    else:
        payload.pop("publish_block_reason", None)


def is_ncaaf_payload_publishable(data: dict[str, Any]) -> bool:
    if not data:
        return False
    if "publishable" in data:
        return bool(data["publishable"])
    return True


def log_publish_blocked(decision: NcaafPublishDecision) -> None:
    msg = (
        "NCAAF publish BLOCKED: "
        f"rated_teams={decision.n_rated_teams} (threshold>={decision.threshold}), "
        f"skip_pbp={decision.skip_pbp}, reason={decision.reason}"
    )
    logger.error(msg)
    print(f"::error title=NCAAF publish blocked::{msg}", flush=True)


def publish_block_summary(decision: NcaafPublishDecision) -> str:
    return (
        f"NCAAF docs not updated — rated teams={decision.n_rated_teams}/"
        f"{decision.threshold}, skip_pbp={decision.skip_pbp} ({decision.reason})"
    )
