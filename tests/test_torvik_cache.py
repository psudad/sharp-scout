"""Torvik committed-cache path (no runner network)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from sharp_scout.health.feeds import FeedHealthRegistry, FeedStatus, record_torvik_ratings
from sharp_scout.ncaam import ratings as ratings_mod
from sharp_scout.ncaam import situational as situational_mod
from sharp_scout.ncaam.ratings import write_successful_retrieval_meta
from sharp_scout.ncaam.torvik_cadence import STALE_MAX_AGE_DAYS, effective_cadence, refresh_due_today
from sharp_scout.ncaam.torvik_cache import best_ratings_cache_path, is_ratings_cache_stale

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ncaam" / "torvik_sample.csv"


def _write_cache(tmp_path: Path, name: str, retrieved_at: datetime) -> Path:
    p = tmp_path / name
    p.write_bytes(FIXTURE.read_bytes())
    write_successful_retrieval_meta(
        p,
        source_url=ratings_mod.TORVIK_URL,
        content_digest=ratings_mod.content_sha256(p),
        retrieved_at=retrieved_at,
    )
    return p


def test_effective_cadence_season_boundaries():
    assert effective_cadence(datetime(2026, 11, 5, tzinfo=timezone.utc).date()) == "daily"
    assert effective_cadence(datetime(2026, 12, 31, tzinfo=timezone.utc).date()) == "daily"
    assert effective_cadence(datetime(2027, 1, 1, tzinfo=timezone.utc).date()) == "weekly"


def test_refresh_due_weekly_only_mondays():
    assert refresh_due_today(datetime(2027, 1, 4, tzinfo=timezone.utc).date()) is True  # Monday
    assert refresh_due_today(datetime(2027, 1, 6, tzinfo=timezone.utc).date()) is False  # Wednesday


def test_best_ratings_by_retrieved_at_not_latest_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    older = _write_cache(
        tmp_path, "ratings_20261101.csv", datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    )
    newer = _write_cache(
        tmp_path, "ratings_20261115.csv", datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
    )
    # ratings_latest with older retrieved_at must lose to newer dated file
    stale_latest = tmp_path / "ratings_latest.csv"
    stale_latest.write_bytes(older.read_bytes())
    write_successful_retrieval_meta(
        stale_latest,
        source_url=ratings_mod.TORVIK_URL,
        content_digest=ratings_mod.content_sha256(stale_latest),
        retrieved_at=datetime(2026, 10, 20, 12, tzinfo=timezone.utc),
    )
    assert best_ratings_cache_path() == newer


def test_stale_thresholds_by_cadence(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    p = _write_cache(tmp_path, "ratings_20261110.csv", datetime(2026, 11, 4, 12, tzinfo=timezone.utc))
    now_fresh = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    assert not is_ratings_cache_stale(p, now=now_fresh)
    now_stale = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    assert is_ratings_cache_stale(p, now=now_stale)
    assert STALE_MAX_AGE_DAYS["daily"] == 2.0


def test_record_torvik_degraded_when_stale():
    reg = FeedHealthRegistry()
    record_torvik_ratings(
        reg,
        ok=True,
        reason="stale cache",
        cache_date="2026-11-01",
        retrieved_at_utc="2026-11-01T12:00:00+00:00",
        age_days=5.0,
        cadence="daily",
        stale=True,
    )
    snap = reg._feeds["torvik_ratings"]
    assert snap.status == FeedStatus.DEGRADED
    assert snap.detail["age_days"] == 5.0


def test_ensure_daily_ratings_never_calls_network(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    _write_cache(tmp_path, "ratings_20261102.csv", datetime(2026, 11, 2, 12, tzinfo=timezone.utc))

    def boom(*_a, **_k):
        raise AssertionError("httpx must not be used on runner path")

    monkeypatch.setattr(httpx, "Client", boom)
    monkeypatch.setattr(httpx, "get", boom)
    path = ratings_mod.ensure_daily_ratings()
    assert path.name == "ratings_20261102.csv"


def test_situational_usage_cache_only(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    monkeypatch.setattr(situational_mod, "NCAAM_DATA", tmp_path)
    usage = {"Duke": {"kyle_filipowski": 30.0}}
    upath = tmp_path / "usage_20261102.json"
    upath.write_text(json.dumps(usage))
    meta = tmp_path / "usage_20261102.json.meta.json"
    meta.write_text(
        json.dumps({"retrieved_at_utc": "2026-11-02T12:00:00+00:00", "retrieval_success": True})
    )

    def boom(*_a, **_k):
        raise AssertionError("httpx must not be used on runner path")

    monkeypatch.setattr(httpx, "Client", boom)
    ctx = situational_mod.Situational(
        datetime(2026, 11, 2, tzinfo=timezone.utc).date(),
        ratings_csv=tmp_path / "ratings.csv",
        offline=False,
    )
    assert ctx._usage_table() == usage


def test_torvik_cadence_setting_override(monkeypatch):
    monkeypatch.setenv("TORVIK_CADENCE", "weekly")
    from sharp_scout.ncaam.torvik_cadence import effective_cadence, torvik_cadence_setting

    assert torvik_cadence_setting() == "weekly"
    assert effective_cadence(datetime(2026, 11, 5).date()) == "weekly"


def test_torvik_refresh_dry_run_no_network(capsys, monkeypatch):
    import scripts.torvik_refresh as tr

    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "test")
    monkeypatch.setattr(tr, "skip_refresh", lambda *a, **k: (False, "would refresh"))

    def boom(*_a, **_k):
        raise AssertionError("network disabled in dry-run")

    monkeypatch.setattr(tr, "_fetch_bytes", boom)
    assert tr.refresh(dry_run=True) == 0
    assert "Dry run" in capsys.readouterr().out