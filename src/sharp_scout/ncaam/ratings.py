"""Barttorvik CSV ratings with daily cache."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from sharp_scout.config import DATA_DIR
from sharp_scout.ncaam.teams import normalize_ncaam
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TORVIK_URL = "https://barttorvik.com/2027_team_results.csv"
UA = "SharpScout/1.0 (github.com/psudad/sharp-scout; NCAAM ratings cache)"
NCAAM_DATA = DATA_DIR / "ncaam"
ET = ZoneInfo("America/New_York")
_RATINGS_DATED = re.compile(r"^ratings_(\d{4})(\d{2})(\d{2})\.csv$")


def ratings_path_for(day: date | None = None) -> Path:
    day = day or datetime.now(ET).date()
    return NCAAM_DATA / f"ratings_{day.strftime('%Y%m%d')}.csv"


def _meta_path_for(csv_path: Path) -> Path:
    return csv_path.with_suffix(csv_path.suffix + ".meta.json")


def content_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_successful_retrieval_meta(
    csv_path: Path,
    *,
    source_url: str,
    content_digest: str,
    retrieved_at: datetime | None = None,
    upstream_http_last_modified_utc: str | None = None,
) -> dict[str, Any]:
    """Persist provenance for a verified successful upstream retrieval (fetch only)."""
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    meta: dict[str, Any] = {
        "source": "barttorvik",
        "source_url": source_url,
        "retrieval_success": True,
        "retrieved_at_utc": retrieved_at.isoformat(),
        "content_sha256": content_digest,
        "content_binding_note": "Digest must match CSV bytes; filename/mtime are not used",
        "upstream_http_last_modified_utc": upstream_http_last_modified_utc,
        "upstream_http_last_modified_note": (
            "Optional HTTP Last-Modified from response; file revision time only — "
            "not ratings snapshot date"
        ),
        "ratings_snapshot_as_of": None,
        "ratings_snapshot_as_of_note": (
            "unknown: Barttorvik team_results CSV has no publisher snapshot/as-of field"
        ),
        "csv_has_snapshot_date_field": False,
    }
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _meta_path_for(csv_path).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


def verify_retrieval_record(path: Path) -> tuple[bool, str, dict[str, Any]]:
    """True when meta documents a successful retrieval bound to current file bytes."""
    if not path.is_file():
        return False, "cache_file_missing", {}
    meta = _load_fetch_meta(path)
    if not meta:
        return False, "retrieval_metadata_missing", {}
    if not meta.get("retrieval_success"):
        return False, "retrieval_not_verified", meta
    digest = meta.get("content_sha256")
    retrieved = meta.get("retrieved_at_utc")
    if not digest or not retrieved:
        return False, "retrieval_metadata_incomplete", meta
    try:
        if content_sha256(path) != str(digest):
            return False, "retrieval_digest_mismatch", meta
    except OSError:
        return False, "cache_file_unreadable", meta
    return True, "", meta


def fetch_torvik_csv(*, dest: Path | None = None) -> Path:
    dest = dest or ratings_path_for()
    dest.parent.mkdir(parents=True, exist_ok=True)
    upstream_last_modified: str | None = None
    with httpx.Client(timeout=60.0, headers={"User-Agent": UA}) as client:
        resp = client.get(TORVIK_URL)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        raw_lm = resp.headers.get("last-modified")
        if raw_lm:
            try:
                upstream_last_modified = parsedate_to_datetime(raw_lm).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, OverflowError):
                upstream_last_modified = None
    _validate_csv(dest)
    latest = NCAAM_DATA / "ratings_latest.csv"
    latest.write_bytes(dest.read_bytes())
    digest = content_sha256(dest)
    meta = write_successful_retrieval_meta(
        dest,
        source_url=TORVIK_URL,
        content_digest=digest,
        upstream_http_last_modified_utc=upstream_last_modified,
    )
    _meta_path_for(latest).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return dest


def _validate_csv(path: Path) -> None:
    with path.open(newline="") as f:
        row = next(csv.DictReader(f), None)
    if not row or not all(k in row for k in ("adjoe", "adjde", "adjt", "team")):
        raise ValueError(f"Torvik CSV missing required columns at {path}")


def load_ratings(path: Path | None = None) -> dict[str, dict[str, float]]:
    p = path or (NCAAM_DATA / "ratings_latest.csv")
    if not p.exists():
        raise FileNotFoundError(f"No NCAAM ratings at {p}")
    out: dict[str, dict[str, float]] = {}
    adjts: list[float] = []
    with p.open(newline="") as f:
        for row in csv.DictReader(f):
            team = str(row.get("team") or "").strip()
            if not team:
                continue
            try:
                adjoe = float(row["adjoe"])
                adjde = float(row["adjde"])
                adjt = float(row["adjt"])
            except (KeyError, ValueError):
                continue
            out[team] = {"adjoe": adjoe, "adjde": adjde, "adjt": adjt}
            adjts.append(adjt)
    lg_adjt = sum(adjts) / len(adjts) if adjts else 70.0
    lg_eff = sum(r["adjoe"] for r in out.values()) / max(len(out), 1)
    for row in out.values():
        row["lg_adjt"] = lg_adjt
        row["lg_eff"] = lg_eff
    return out


def cache_date_from_path(path: Path) -> date | None:
    """Local cache acquisition label from ``ratings_YYYYMMDD.csv`` (not model snapshot date)."""
    m = _RATINGS_DATED.match(path.name)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _load_fetch_meta(path: Path) -> dict[str, Any]:
    mp = _meta_path_for(path)
    if mp.is_file():
        try:
            return json.loads(mp.read_text())
        except (OSError, ValueError):
            pass
    return {}


def ratings_provenance_for_path(path: Path) -> dict[str, Any]:
    """Acquisition provenance for Sharp 3 display (verified retrieval + digest binding)."""
    verified, fail_reason, meta = verify_retrieval_record(path)
    cache_dt = cache_date_from_path(path)
    return {
        "source": meta.get("source") or "barttorvik",
        "source_url": meta.get("source_url") or TORVIK_URL,
        "cache_path": str(path),
        "cache_date_et": cache_dt.isoformat() if cache_dt else None,
        "cache_date_note": "Filename label only; not used for retrieval freshness",
        "retrieval_verified": verified,
        "retrieval_unavailable_reason": fail_reason if not verified else None,
        "retrieved_at_utc": meta.get("retrieved_at_utc"),
        "content_sha256": meta.get("content_sha256"),
        "ratings_snapshot_as_of": meta.get("ratings_snapshot_as_of"),
        "ratings_snapshot_as_of_note": meta.get("ratings_snapshot_as_of_note")
        or "unknown: publisher does not declare efficiency snapshot date in CSV",
        "upstream_http_last_modified_utc": meta.get("upstream_http_last_modified_utc"),
        "upstream_http_last_modified_note": meta.get("upstream_http_last_modified_note"),
    }


def ratings_for_team(name: str, ratings: dict[str, dict[str, float]]) -> dict[str, float] | None:
    canon = normalize_ncaam(name) or name
    return ratings.get(canon)


def _fallback_ratings_path() -> Path | None:
    latest = NCAAM_DATA / "ratings_latest.csv"
    if latest.exists():
        return latest
    dated = sorted(NCAAM_DATA.glob("ratings_20*.csv"), reverse=True)
    return dated[0] if dated else None


def _fetch_failure_path(day: date | None = None) -> Path:
    day = day or datetime.now(ET).date()
    return NCAAM_DATA / f"ratings_fetch_failed_{day.strftime('%Y%m%d')}.json"


def _load_fetch_failure(day: date | None = None) -> dict[str, Any] | None:
    p = _fetch_failure_path(day)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {"date": (day or datetime.now(ET).date()).isoformat(), "recorded": True}


def daily_fetch_state_paths_for_commit() -> list[str]:
    """Repo-relative paths to stage on heartbeat commits so fetch backoff survives checkouts."""
    from sharp_scout.config import ROOT

    paths: list[str] = []
    day = datetime.now(ET).date()
    for p in (_fetch_failure_path(day), ratings_path_for(day)):
        if p.is_file():
            try:
                paths.append(p.relative_to(ROOT).as_posix())
            except ValueError:
                paths.append(str(p))
            meta = _meta_path_for(p)
            if meta.is_file():
                paths.append(meta.relative_to(ROOT).as_posix())
    return paths


def write_fetch_failure(
    exc: BaseException,
    *,
    day: date | None = None,
    attempted_at: datetime | None = None,
) -> dict[str, Any]:
    day = day or datetime.now(ET).date()
    attempted_at = attempted_at or datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "date_et": day.isoformat(),
        "source_url": TORVIK_URL,
        "attempted_at_utc": attempted_at.isoformat(),
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
    p = _fetch_failure_path(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def _log_ratings_selection(path: Path, *, reason: str) -> None:
    cache_dt = cache_date_from_path(path)
    label = cache_dt.isoformat() if cache_dt else path.name
    logger.info(
        "NCAAM Barttorvik ratings: %s file=%s cache_date_et=%s",
        reason,
        path.name,
        label,
    )


def ensure_daily_ratings(*, demo: bool = False, fixture: Path | None = None) -> Path:
    """Return path to Torvik cache used for picks.

    - If ``ratings_{today_et}.csv`` exists, return it **without re-fetching** (content may be
      from an earlier run today).
    - On fetch success, writes HTTP body to today's dated path (acquisition label = today ET).
    - On fetch failure, falls back to ``ratings_latest.csv`` or the newest dated cache — **same
      bytes may be older than the filename suggests** when fallback ≠ today.
    CSV payload has **no** embedded snapshot/as-of date.
    """
    if demo and fixture and fixture.exists():
        dest = NCAAM_DATA / "ratings_latest.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(fixture.read_bytes())
        return dest
    et_day = datetime.now(ET).date()
    today_path = ratings_path_for(et_day)
    if today_path.exists():
        _log_ratings_selection(today_path, reason="using committed or prior fetch for today ET")
        return today_path
    if demo:
        fx = DATA_DIR.parent / "tests" / "fixtures" / "ncaam" / "torvik_sample.csv"
        if fx.exists():
            latest = NCAAM_DATA / "ratings_latest.csv"
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_bytes(fx.read_bytes())
            return latest
    if _load_fetch_failure(et_day):
        fb = _fallback_ratings_path()
        if fb is None:
            raise FileNotFoundError(
                f"Torvik fetch already failed today ({et_day.isoformat()}) and no cached ratings exist"
            )
        _log_ratings_selection(
            fb,
            reason=f"skipping re-fetch (failed earlier today ET; see {_fetch_failure_path(et_day).name})",
        )
        return fb
    try:
        dest = fetch_torvik_csv(dest=today_path)
        _log_ratings_selection(dest, reason="fetched fresh Barttorvik CSV for today ET")
        return dest
    except Exception as exc:  # noqa: BLE001
        write_fetch_failure(exc, day=et_day)
        logger.warning(
            "Torvik daily fetch failed (%s); will not retry until next ET day (%s)",
            exc,
            et_day.isoformat(),
        )
        fb = _fallback_ratings_path()
        if fb is None:
            raise
        _log_ratings_selection(fb, reason="using fallback cache after fetch failure")
        return fb
