"""Gate NCAAF GitHub Pages / docs publishing (model QA thresholds unchanged)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sharp_scout.qa.gate import MIN_RATED_TEAMS_NCAAF

logger = logging.getLogger(__name__)

# CLI exit code when the pipeline completes but docs/ publish was blocked.
# GitHub Actions workflows treat only this code as a non-fatal publish skip (see
# scripts/ncaaf_ci_post_run.sh). Must stay in sync with that script.
EXIT_PUBLISH_BLOCKED = 3


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
) -> NcaafPublishDecision:
    """Return whether this pipeline payload may be written to committed docs/.

    Only the approved provenance checks: demo mode, skip_pbp, or fewer than 80 rated
    teams. Other QA Layer 1 failures are logged by ``apply_qa_gate`` but do not block
    publishing here.
    """
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

    return NcaafPublishDecision(True, "ok", n_teams, skip_pbp)


def may_append_ncaaf_ledger(
    payload: dict[str, Any],
    *,
    skip_pbp: bool = False,
    demo: bool = False,
) -> bool:
    """Ledger locks / paper rows require the same provenance as a public board publish."""
    return decide_ncaaf_publish(payload, skip_pbp=skip_pbp).publishable and not demo


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
