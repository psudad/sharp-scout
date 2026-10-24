"""Backfill shadow ledger from committed NCAAF signal snapshots."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Iterator

from sharp_scout.ncaaf.shadow.capture import record_from_pipeline

logger = logging.getLogger(__name__)

DEFAULT_SNAPSHOT_PATH = "docs/latest_ncaaf_signals.json"


def _git_commits_for(path: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "log", "--format=%H", "--", path],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if not out:
        return []
    return out.split("\n")


def _git_show_file(commit: str, path: str) -> dict[str, Any] | None:
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{commit}:{path}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def iter_historical_snapshots(
    path: str = DEFAULT_SNAPSHOT_PATH,
    *,
    repo_root: Path | None = None,
) -> Iterator[dict[str, Any]]:
    root = repo_root or Path.cwd()
    commits = _git_commits_for(path)
    # Oldest first so first_seen timestamps follow history.
    for commit in reversed(commits):
        payload = _git_show_file(commit, path)
        if not payload or not payload.get("signals"):
            continue
        payload["_git_commit"] = commit
        yield payload


def backfill_from_git_history(
    path: str = DEFAULT_SNAPSHOT_PATH,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Replay git-tracked signal snapshots into the shadow ledger."""
    total_snapshots = 0
    per_bucket_added = {"ev_12_16": 0, "ev_16_plus": 0, "cert_miss": 0}

    for payload in iter_historical_snapshots(path, repo_root=repo_root):
        total_snapshots += 1
        before = _ledger_keys()
        res = record_from_pipeline(
            payload.get("signals") or [],
            signals_payload=payload,
            season=payload.get("season"),
            week=payload.get("week"),
        )
        after = _ledger_keys()
        new_keys = after - before
        for key in new_keys:
            bucket = key.split("|")[-1]
            if bucket in per_bucket_added:
                per_bucket_added[bucket] += 1

    logger.info(
        "Backfill complete: snapshots=%d new_by_bucket=%s",
        total_snapshots,
        per_bucket_added,
    )
    return {
        "snapshots_processed": total_snapshots,
        "new_rows_by_bucket": per_bucket_added,
        "new_rows_total": sum(per_bucket_added.values()),
    }


def _ledger_keys() -> set[str]:
    from sharp_scout.ncaaf.shadow.ledger import load_ledger, play_key

    ledger = load_ledger()
    return {
        play_key(p.get("event_id"), p.get("side"), bucket=p.get("bucket") or "")
        for p in ledger.get("plays") or []
    }
