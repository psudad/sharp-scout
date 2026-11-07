"""Barttorvik CSV ratings with daily cache."""

from __future__ import annotations

import csv
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
    meta = {
        "source_url": TORVIK_URL,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_http_last_modified_utc": upstream_last_modified,
        "upstream_http_last_modified_note": (
            "HTTP Last-Modified from Barttorvik CSV response; file revision time only — "
            "not a verified efficiency snapshot/as-of date and not used as ratings_as_of"
        ),
        "csv_has_snapshot_date_field": False,
    }
    _meta_path_for(dest).write_text(json.dumps(meta, indent=2) + "\n")
    _meta_path_for(latest).write_bytes(_meta_path_for(dest).read_bytes())
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
    # ratings_latest.meta may sit beside ratings_latest.csv
    if path.name == "ratings_latest.csv":
        dated = sorted(NCAAM_DATA.glob("ratings_20*.csv.meta.json"), reverse=True)
        if dated:
            try:
                return json.loads(dated[0].read_text())
            except (OSError, ValueError):
                pass
    return {}


def ratings_provenance_for_path(path: Path) -> dict[str, Any]:
    """Audit trail for Sharp 3 display. ``ratings_as_of`` is only set from verified upstream fields."""
    fetched_at: str | None = None
    if path.is_file():
        fetched_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    cache_dt = cache_date_from_path(path)
    meta = _load_fetch_meta(path)
    # Torvik team_results CSV columns (adjoe, adjde, adjt, …) carry no snapshot/as-of date.
    ratings_as_of = meta.get("ratings_source_as_of")
    verified = bool(ratings_as_of)
    derivation = meta.get("ratings_as_of_derivation") if verified else (
        "unavailable: Barttorvik CSV has no snapshot-date field; "
        "cache filename is acquisition label only"
    )
    return {
        "source": "barttorvik",
        "source_url": TORVIK_URL,
        "cache_path": str(path),
        "cache_date_et": cache_dt.isoformat() if cache_dt else None,
        "cache_date_derivation": (
            "filename ratings_YYYYMMDD.csv (local write target when fetch succeeds)"
            if cache_dt
            else "unknown"
        ),
        "cache_date_note": "Not equivalent to efficiency model snapshot date",
        "ratings_as_of": ratings_as_of,
        "ratings_as_of_verified": verified,
        "ratings_as_of_derivation": derivation,
        "fetched_at_utc": meta.get("fetched_at_utc") or fetched_at,
        "fetched_at_note": "When this cache file was written locally",
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
        return today_path
    if demo:
        fx = DATA_DIR.parent / "tests" / "fixtures" / "ncaam" / "torvik_sample.csv"
        if fx.exists():
            latest = NCAAM_DATA / "ratings_latest.csv"
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_bytes(fx.read_bytes())
            return latest
    try:
        return fetch_torvik_csv(dest=today_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Torvik daily fetch failed (%s); using last cached file", exc)
        fb = _fallback_ratings_path()
        if fb is None:
            raise
        return fb
