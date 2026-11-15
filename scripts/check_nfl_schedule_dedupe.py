#!/usr/bin/env python3
"""Skip delayed GitHub schedule runs when this workflow already ran for the same slot.

External backup dispatches pipeline.yml via workflow_dispatch when GitHub is late.
When GitHub's scheduled run finally arrives, we must not spend Odds API credits again.

Backup counts a slot covered if a run was created from slot-5min through slot+2h.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

WORKFLOW_FILE = "pipeline.yml"
SLOT_LEAD = timedelta(minutes=5)
# Match backup watchdog window upper bound (slot + 2h); use `now` as the live upper bound.

_BLOCKING_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})
_BLOCKING_CONCLUSIONS = frozenset({"success", None})  # in-flight runs have null conclusion


def _github_utc_dow(dt: datetime) -> int:
    """GitHub Actions cron day-of-week: 0=Sunday … 6=Saturday."""
    return (dt.weekday() + 1) % 7


def _cron_dow_matches(dt: datetime, dow_field: str) -> bool:
    if dow_field == "*":
        return True
    allowed: set[int] = set()
    for part in dow_field.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            allowed.update(range(int(start_s), int(end_s) + 1))
        else:
            allowed.add(int(part))
    return _github_utc_dow(dt) in allowed


def parse_cron_fields(cron: str) -> tuple[int, int, str]:
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError(f"expected 5 cron fields, got {len(parts)}: {cron!r}")
    minute = int(parts[0])
    hour = int(parts[1])
    dow = parts[4]
    return minute, hour, dow


def most_recent_slot_utc(cron: str, now: datetime) -> datetime | None:
    """Most recent occurrence of this cron at or before ``now`` (UTC)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    minute, hour, dow = parse_cron_fields(cron)
    candidate = datetime(now.year, now.month, now.day, hour, minute, tzinfo=timezone.utc)

    for _ in range(8):
        if candidate <= now and _cron_dow_matches(candidate, dow):
            return candidate
        candidate -= timedelta(days=1)
    return None


def _parse_github_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _run_blocks_dedupe(run: dict) -> bool:
    status = str(run.get("status") or "")
    conclusion = run.get("conclusion")
    if status in _BLOCKING_STATUSES:
        return True
    if status == "completed":
        if conclusion == "success":
            return True
        # failed / cancelled / skipped / etc. — allow retry
        return False
    return conclusion in _BLOCKING_CONCLUSIONS


def fetch_workflow_runs(
    repo: str,
    token: str,
    created_gte: datetime,
    created_lte: datetime,
) -> list[dict]:
    """List workflow runs created in [created_gte, created_lte] (paginated)."""
    gte = created_gte.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lte = created_lte.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    runs: list[dict] = []
    page = 1
    while True:
        url = f"{base}?per_page=100&created=%3E%3D{gte}&page={page}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode())
        batch = payload.get("workflow_runs") or []
        if not batch:
            break
        for run in batch:
            created = _parse_github_ts(run.get("created_at"))
            if created is None:
                continue
            if created > created_lte:
                continue
            runs.append(run)
        if len(batch) < 100:
            break
        page += 1
        if page > 10:
            break
    return runs


def should_skip_scheduled_run(
    *,
    cron: str,
    now: datetime,
    current_run_id: str | None,
    repo: str | None,
    token: str | None,
) -> tuple[bool, str]:
    """Return (skip, reason). API / config problems fail open (do not skip)."""
    slot = most_recent_slot_utc(cron, now)
    if slot is None:
        return False, f"could not resolve slot for cron {cron!r}"

    window_start = slot - SLOT_LEAD
    print(f"Slot {slot.isoformat()} (cron={cron!r}); dedupe window [{window_start.isoformat()}, {now.isoformat()}]")

    if not repo or not token:
        return False, "missing GITHUB_REPOSITORY or token — fail open"

    try:
        runs = fetch_workflow_runs(repo, token, window_start, now)
    except Exception as exc:  # noqa: BLE001
        return False, f"GitHub API error ({exc}) — fail open"

    for run in runs:
        if current_run_id and str(run.get("id")) == str(current_run_id):
            continue
        created = _parse_github_ts(run.get("created_at"))
        if created is None or created < window_start or created > now:
            continue
        if not _run_blocks_dedupe(run):
            continue
        ev = run.get("event") or "?"
        rid = run.get("id")
        msg = (
            f"skip: prior run id={rid} event={ev} status={run.get('status')} "
            f"conclusion={run.get('conclusion')} created={run.get('created_at')}"
        )
        return True, msg

    return False, "no blocking prior run in window"


def _write_output(skip: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"skip={'true' if skip else 'false'}\n")


def main() -> None:
    event = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    if event != "schedule":
        print("Non-schedule event — never skip")
        _write_output(False)
        return

    cron = os.environ.get("GITHUB_SCHEDULE_CRON", "").strip()
    if not cron:
        print("Missing GITHUB_SCHEDULE_CRON — fail open")
        _write_output(False)
        return

    now = datetime.now(timezone.utc)
    skip, why = should_skip_scheduled_run(
        cron=cron,
        now=now,
        current_run_id=os.environ.get("GITHUB_RUN_ID"),
        repo=os.environ.get("GITHUB_REPOSITORY"),
        token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
    )
    print(why)
    _write_output(skip)


if __name__ == "__main__":
    main()