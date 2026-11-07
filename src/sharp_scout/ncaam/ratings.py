"""Barttorvik CSV ratings with daily cache."""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime, timezone
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


def fetch_torvik_csv(*, dest: Path | None = None) -> Path:
    dest = dest or ratings_path_for()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60.0, headers={"User-Agent": UA}) as client:
        resp = client.get(TORVIK_URL)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    _validate_csv(dest)
    latest = NCAAM_DATA / "ratings_latest.csv"
    latest.write_bytes(dest.read_bytes())
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


def ratings_as_of_from_path(path: Path) -> date | None:
    """Snapshot date from ``ratings_YYYYMMDD.csv`` filename only (never mtime)."""
    m = _RATINGS_DATED.match(path.name)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def ratings_provenance_for_path(path: Path) -> dict[str, Any]:
    """Provenance for Sharp 3 / audit: Barttorvik source, as-of from filename, fetch mtime separate."""
    fetched_at: str | None = None
    if path.is_file():
        fetched_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    as_of = ratings_as_of_from_path(path)
    return {
        "source": "barttorvik",
        "source_url": TORVIK_URL,
        "cache_path": str(path),
        "ratings_as_of": as_of.isoformat() if as_of else None,
        "ratings_as_of_derivation": "filename ratings_YYYYMMDD.csv" if as_of else "unknown",
        "fetched_at_utc": fetched_at,
        "fetched_at_note": "Cache file mtime when downloaded/copied; not Barttorvik snapshot date",
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
