"""Committed Torvik cache selection (runners never fetch upstream)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.ncaam import ratings as ratings_mod
from sharp_scout.ncaam.ratings import (
    _meta_path_for,
    cache_date_from_path,
    verify_retrieval_record,
)
from sharp_scout.ncaam.torvik_cadence import (
    effective_cadence,
    parse_retrieved_at,
    stale_threshold_days,
)

logger = logging.getLogger(__name__)

USAGE_LATEST = "usage_latest.json"


def _ncaam_data_dir(data_dir: Path | None = None) -> Path:
    if data_dir is not None:
        return data_dir
    return ratings_mod.NCAAM_DATA


def _rating_csv_candidates(data_dir: Path | None = None) -> list[Path]:
    root = _ncaam_data_dir(data_dir)
    if not root.is_dir():
        return []
    paths = list(root.glob("ratings_20*.csv"))
    latest = root / "ratings_latest.csv"
    if latest.is_file():
        paths.append(latest)
    return paths


def retrieved_at_for_path(path: Path) -> datetime | None:
    """Best-effort retrieval timestamp: meta first, then ET date in filename."""
    _ok, _reason, meta = verify_retrieval_record(path)
    if meta.get("retrieved_at_utc"):
        return parse_retrieved_at(str(meta["retrieved_at_utc"]))
    mp = _meta_path_for(path)
    if mp.is_file():
        try:
            raw = json.loads(mp.read_text())
            dt = parse_retrieved_at(str(raw.get("retrieved_at_utc") or ""))
            if dt:
                return dt
        except (OSError, ValueError, TypeError):
            pass
    cache_dt = cache_date_from_path(path)
    if cache_dt:
        return datetime(cache_dt.year, cache_dt.month, cache_dt.day, 12, 0, tzinfo=ratings_mod.ET)
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except OSError:
        return None


def best_ratings_cache_path(*, data_dir: Path | None = None) -> Path | None:
    """Newest committed ratings file by ``retrieved_at_utc`` (not filename / latest alias)."""
    best: Path | None = None
    best_at: datetime | None = None
    for path in _rating_csv_candidates(data_dir):
        if "fetch_failed" in path.name:
            continue
        at = retrieved_at_for_path(path)
        if at is None:
            continue
        if best_at is None or at > best_at:
            best_at = at
            best = path
    return best


def cache_age_days(path: Path, *, now: datetime | None = None) -> float | None:
    now = now or datetime.now(timezone.utc)
    at = retrieved_at_for_path(path)
    if at is None:
        return None
    return max(0.0, (now - at).total_seconds() / 86400.0)


def is_ratings_cache_stale(path: Path, *, now: datetime | None = None, day: date | None = None) -> bool:
    age = cache_age_days(path, now=now)
    if age is None:
        return True
    return age > stale_threshold_days(day)


def ratings_cache_health_info(
    path: Path | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if path is None or not path.is_file():
        return {
            "ok": False,
            "stale": True,
            "age_days": None,
            "cadence": effective_cadence(now.astimezone(ratings_mod.ET).date()),
            "retrieved_at_utc": None,
            "cache_date_et": None,
        }
    age = cache_age_days(path, now=now)
    cadence = effective_cadence(now.astimezone(ratings_mod.ET).date())
    stale = is_ratings_cache_stale(path, now=now)
    at = retrieved_at_for_path(path)
    cache_dt = cache_date_from_path(path)
    return {
        "ok": True,
        "stale": stale,
        "age_days": age,
        "cadence": cadence,
        "retrieved_at_utc": at.isoformat() if at else None,
        "cache_date_et": cache_dt.isoformat() if cache_dt else None,
    }


def _usage_json_candidates(data_dir: Path | None = None) -> list[Path]:
    root = _ncaam_data_dir(data_dir)
    if not root.is_dir():
        return []
    paths = [p for p in root.glob("usage_20*.json") if not p.name.endswith(".meta.json")]
    latest = root / USAGE_LATEST
    if latest.is_file():
        paths.append(latest)
    return paths


def best_usage_cache_path(*, data_dir: Path | None = None) -> Path | None:
    best: Path | None = None
    best_at: datetime | None = None
    for path in _usage_json_candidates(data_dir):
        meta_path = Path(str(path) + ".meta.json")
        at: datetime | None = None
        if meta_path.is_file():
            try:
                raw = json.loads(meta_path.read_text())
                at = parse_retrieved_at(str(raw.get("retrieved_at_utc") or ""))
            except (OSError, ValueError, TypeError):
                at = None
        if at is None:
            m = path.name.removeprefix("usage_").removesuffix(".json")
            if len(m) == 8 and m.isdigit():
                at = datetime(int(m[0:4]), int(m[4:6]), int(m[6:8]), 12, 0, tzinfo=ratings_mod.ET)
        if at is None:
            continue
        if best_at is None or at > best_at:
            best_at = at
            best = path
    return best


def write_usage_meta(json_path: Path, *, source_url: str, retrieved_at: datetime | None = None) -> dict[str, Any]:
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    meta = {
        "source": "barttorvik",
        "source_url": source_url,
        "retrieval_success": True,
        "retrieved_at_utc": retrieved_at.isoformat(),
    }
    meta_path = Path(str(json_path) + ".meta.json")
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta