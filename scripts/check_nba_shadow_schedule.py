#!/usr/bin/env python3
"""CI gate: scheduled NBA shadow runs match the seasonal cron for the intended ET slot."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nba.schedule_guard import (  # noqa: E402
    ET,
    catchup_run_allowed,
    intended_et_date_from_cron,
    is_backup_cron,
    is_catchup_cron,
    primary_scan_satisfied_for_et_date,
    scan_fresh_for_et_date,
    scheduled_cron_run_allowed,
)

SCAN_STEP_NAME = "Run NBA shadow pipeline"
from sharp_scout.scheduler.odds_credit_pause import (  # noqa: E402
    ODDS_CREDIT_RESUME_ET_DATE,
    scheduled_odds_pause_active,
)


def _first_tip_utc(now: datetime) -> datetime | None:
    """First NBA tip-off of today's ET slate (ESPN, no Odds API). None if unknown."""
    try:
        from sharp_scout.data.espn_nba import fetch_espn_nba_first_tip_utc

        return fetch_espn_nba_first_tip_utc(now.astimezone(ET).date())
    except Exception as exc:  # noqa: BLE001
        print(f"First tip-off lookup failed ({exc}); using fixed late-start limit")
        return None


def _scan_attempts_today(now: datetime) -> int:
    """How many runs of this workflow already executed the scan step today (ET).

    Uses the GitHub API with the job token. Fails open (returns 0) when unavailable, so
    the cap never blocks a needed scan; freshness still stops repeat scans once one lands.
    """
    import json
    import urllib.request

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    this_run = os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:
        return 0
    et_day = now.astimezone(ET).date()
    start_utc = datetime.combine(et_day, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    def get(url: str) -> dict:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    try:
        created = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        runs = get(
            f"https://api.github.com/repos/{repo}/actions/workflows/nba-shadow.yml/runs"
            f"?per_page=100&created=%3E%3D{created}"
        ).get("workflow_runs") or []
        n = 0
        for run in runs:
            if str(run.get("id")) == str(this_run):
                continue
            jobs = get(run["jobs_url"]).get("jobs") or []
            for job in jobs:
                for step in job.get("steps") or []:
                    if step.get("name") == SCAN_STEP_NAME and step.get("conclusion") in (
                        "success",
                        "failure",
                        "cancelled",
                    ):
                        n += 1
        return n
    except Exception as exc:  # noqa: BLE001
        print(f"Could not count today's scan attempts ({exc}); assuming 0")
        return 0


def main() -> None:
    now = datetime.now(timezone.utc)
    cron = os.environ.get("GITHUB_SCHEDULE_CRON", "").strip()
    first_tip = _first_tip_utc(now) if cron else None
    if first_tip is not None:
        print(f"First tip-off today: {first_tip.astimezone(ET).isoformat()} ET")
    else:
        print("First tip-off unknown; late starts limited to the fixed window")

    if cron and is_catchup_cron(cron):
        et_day = now.astimezone(ET).date()
        fresh = scan_fresh_for_et_date(et_day)
        attempts = _scan_attempts_today(now) if first_tip is not None else 0
        ok, why = catchup_run_allowed(
            now, first_tip_utc=first_tip, scan_fresh=fresh, attempts_today=attempts
        )
        skip_props = ok and scheduled_odds_pause_active(now)
        print(f"Catch-up check ({cron!r}): {'RUN' if ok else 'skip'} - {why}")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as fh:
                fh.write(f"run={'true' if ok else 'false'}\n")
                fh.write(f"skip_props={'true' if skip_props else 'false'}\n")
        return

    ok = bool(cron) and scheduled_cron_run_allowed(cron, now, first_tip_utc=first_tip)
    skip_props = ok and scheduled_odds_pause_active(now)

    if ok and is_backup_cron(cron):
        et_day = intended_et_date_from_cron(cron, now, first_tip_utc=first_tip)
        if et_day is not None and primary_scan_satisfied_for_et_date(et_day):
            print(
                f"Skipping backup run: primary scan already recorded for {et_day.isoformat()} ET "
                f"(cron={cron!r})"
            )
            ok = False

    if ok:
        msg = f"Allowed scheduled run: cron={cron!r} now={now.isoformat()}"
        if skip_props:
            msg += f" (game lines only — props paused until {ODDS_CREDIT_RESUME_ET_DATE.isoformat()} ET)"
        print(msg)
    else:
        print(
            f"Skipping scheduled run: cron={cron!r} now={now.isoformat()} "
            "(wrong seasonal line, too late / at or after first tip, backup unnecessary, or unknown cron)"
        )

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if ok else 'false'}\n")
            fh.write(f"skip_props={'true' if skip_props else 'false'}\n")


if __name__ == "__main__":
    main()
