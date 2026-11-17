#!/usr/bin/env python3
"""Refresh committed Barttorvik caches from a non-CI box (single GET each, gh api commit).

Required env: GH_TOKEN (or GITHUB_TOKEN), GITHUB_REPOSITORY (owner/repo).
Optional: TORVIK_CADENCE=daily|weekly|auto
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.ncaam.ratings import (  # noqa: E402
    TORVIK_URL,
    NCAAM_DATA,
    _validate_csv,
    content_sha256,
    count_teams_in_csv,
    write_successful_retrieval_meta,
)
from sharp_scout.ncaam.situational import STAR_USAGE, _norm_name, _torvik_year  # noqa: E402
from sharp_scout.ncaam.torvik_cadence import (  # noqa: E402
    TORVIK_UA,
    effective_cadence,
    freshness_window,
    parse_retrieved_at,
    refresh_due_today,
)
from sharp_scout.ncaam.torvik_cache import USAGE_LATEST, write_usage_meta  # noqa: E402
from sharp_scout.ncaam.teams import normalize_ncaam  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

ET = ZoneInfo("America/New_York")
ADVSTATS_URL = "https://barttorvik.com/getadvstats.php?year={year}&csv=1"
MIN_TEAMS = 50


def _repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        raise SystemExit("GITHUB_REPOSITORY is required (owner/repo)")
    return repo


def _token() -> str:
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not tok:
        raise SystemExit("GH_TOKEN (or GITHUB_TOKEN) is required for gh api commits")
    return tok


def _gh_api(*args: str, input_text: str | None = None) -> dict:
    cmd = ["gh", "api", *args]
    env = {**os.environ, "GH_TOKEN": _token(), "GITHUB_TOKEN": _token()}
    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"gh api failed: {args}")
    if not proc.stdout.strip():
        return {}
    return json.loads(proc.stdout)


def _gh_get_file_sha(repo: str, path: str, ref: str = "main") -> tuple[str | None, bytes | None]:
    import urllib.parse

    q = urllib.parse.quote(path, safe="")
    try:
        data = _gh_api("GET", f"repos/{repo}/contents/{q}?ref={ref}")
    except RuntimeError:
        return None, None
    content_b64 = data.get("content")
    sha = data.get("sha")
    raw = None
    if content_b64:
        raw = base64.b64decode(str(content_b64).replace("\n", ""))
    return sha, raw


def _gh_put_file(
    repo: str,
    path: str,
    content: bytes,
    message: str,
    *,
    sha: str | None = None,
    max_retries: int = 3,
) -> None:
    import urllib.parse

    q = urllib.parse.quote(path, safe="")
    body_b64 = base64.b64encode(content).decode("ascii")
    payload = {
        "message": message,
        "content": body_b64,
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            if attempt:
                sha_now, _ = _gh_get_file_sha(repo, path)
                if sha_now:
                    payload["sha"] = sha_now
            _gh_api("--method", "PUT", f"repos/{repo}/contents/{q}", input_text=json.dumps(payload))
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise SystemExit(f"Failed to commit {path} after {max_retries} tries: {last_err}")


def _meta_bytes(meta: dict) -> bytes:
    return (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode()


def _committed_retrieved_at(repo: str, rel_path: str) -> datetime | None:
    meta_rel = rel_path + ".meta.json"
    _sha, raw = _gh_get_file_sha(repo, meta_rel)
    if not raw:
        return None
    try:
        meta = json.loads(raw)
        return parse_retrieved_at(str(meta.get("retrieved_at_utc") or ""))
    except (ValueError, json.JSONDecodeError, TypeError):
        return None


def skip_refresh(repo: str, *, now: datetime) -> tuple[bool, str]:
    et_day = now.astimezone(ET).date()
    if not refresh_due_today(et_day):
        return True, f"cadence={effective_cadence(et_day)}: not a scheduled refresh day"
    rel = "data/ncaam/ratings_latest.csv"
    retrieved = _committed_retrieved_at(repo, rel)
    if retrieved is None:
        return False, "no ratings_latest meta on main"
    age = now - retrieved
    if age <= freshness_window(et_day):
        return True, f"main cache fresh ({age.total_seconds() / 3600:.1f}h old, within window)"
    return False, f"cache older than freshness window ({age.days}d)"


def _fetch_bytes(url: str) -> tuple[bytes, str | None]:
    with httpx.Client(timeout=90.0, headers={"User-Agent": TORVIK_UA}) as client:
        resp = client.get(url)
        if resp.status_code == 403:
            raise SystemExit(f"barttorvik returned 403 Forbidden for {url} (runner/box IP blocked?)")
        resp.raise_for_status()
        upstream_lm: str | None = None
        raw_lm = resp.headers.get("last-modified")
        if raw_lm:
            try:
                upstream_lm = parsedate_to_datetime(raw_lm).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, OverflowError):
                upstream_lm = None
        return resp.content, upstream_lm


def _build_usage_table(advstats_text: str) -> dict[str, dict[str, float]]:
    usage: dict[str, dict[str, float]] = {}
    for row in csv.reader(advstats_text.splitlines()):
        if len(row) < 7:
            continue
        try:
            usg = float(row[6])
        except ValueError:
            continue
        if usg <= STAR_USAGE:
            continue
        team = normalize_ncaam(row[1]) or row[1]
        usage.setdefault(team, {})[_norm_name(row[0])] = usg
    return usage


def refresh(*, dry_run: bool = False, force: bool = False) -> int:
    now = datetime.now(timezone.utc)
    et_day = now.astimezone(ET).date()
    repo = _repo()

    skip, why = (False, "forced") if force else skip_refresh(repo, now=now)
    if skip:
        print(f"Skip: {why}")
        return 0
    print(f"Proceed: {why}")

    day_tag = et_day.strftime("%Y%m%d")
    ratings_rel = f"data/ncaam/ratings_{day_tag}.csv"
    ratings_latest_rel = "data/ncaam/ratings_latest.csv"
    usage_rel = f"data/ncaam/usage_{day_tag}.json"
    usage_latest_rel = f"data/ncaam/usage_latest.json"

    if dry_run:
        print(
            f"Dry run: would GET {TORVIK_URL} and advstats year={_torvik_year(et_day)}, "
            f"then commit {ratings_rel}, meta, {ratings_latest_rel}, meta, {usage_rel}, meta, {usage_latest_rel}"
        )
        return 0

    csv_bytes, upstream_lm = _fetch_bytes(TORVIK_URL)
    dest = NCAAM_DATA / f"ratings_{day_tag}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(csv_bytes)
    _validate_csv(dest)
    teams = count_teams_in_csv(dest)
    if teams < MIN_TEAMS:
        raise SystemExit(f"Torvik CSV has only {teams} teams (expected >={MIN_TEAMS})")
    existing = count_teams_in_csv(DATA_DIR / "ncaam" / "ratings_latest.csv") if (DATA_DIR / "ncaam" / "ratings_latest.csv").is_file() else 0
    if existing and teams < int(existing * 0.9):
        raise SystemExit(f"Torvik CSV team count {teams} is far below prior cache {existing}")

    digest = content_sha256(dest)
    meta = write_successful_retrieval_meta(
        dest,
        source_url=TORVIK_URL,
        content_digest=digest,
        retrieved_at=now,
        upstream_http_last_modified_utc=upstream_lm,
    )

    year = _torvik_year(et_day)
    adv_bytes, _adv_lm = _fetch_bytes(ADVSTATS_URL.format(year=year))
    usage = _build_usage_table(adv_bytes.decode("utf-8", errors="replace"))
    if not usage:
        raise SystemExit("advstats CSV produced empty usage table")
    usage_json = (json.dumps(usage, separators=(",", ":"), sort_keys=True) + "\n").encode()

    usage_path = NCAAM_DATA / f"usage_{day_tag}.json"
    usage_path.write_bytes(usage_json)
    usage_meta = write_usage_meta(usage_path, source_url=ADVSTATS_URL.format(year=year), retrieved_at=now)

    msg = f"Torvik cache refresh {day_tag} ({teams} teams, cadence={effective_cadence(et_day)})"
    pairs = [
        (ratings_rel, csv_bytes, None),
        (ratings_rel + ".meta.json", _meta_bytes(meta), None),
        (ratings_latest_rel, csv_bytes, None),
        (ratings_latest_rel + ".meta.json", _meta_bytes(meta), None),
        (usage_rel, usage_json, None),
        (usage_rel + ".meta.json", _meta_bytes(usage_meta), None),
        (usage_latest_rel, usage_json, None),
        (usage_latest_rel + ".meta.json", _meta_bytes(usage_meta), None),
    ]
    for rel, content, _ in pairs:
        sha, _ = _gh_get_file_sha(repo, rel)
        _gh_put_file(repo, rel, content, msg, sha=sha)
        print(f"Committed {rel}")

    print("Done.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh committed Barttorvik caches (box only).")
    parser.add_argument("--dry-run", action="store_true", help="No network; print planned actions.")
    parser.add_argument("--force", action="store_true", help="Ignore cadence / freshness skip checks.")
    args = parser.parse_args()
    return refresh(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())