"""Unit tests for scripts/torvik_refresh.py (no network)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import scripts.torvik_refresh as tr

ET = ZoneInfo("America/New_York")


def test_gh_api_get_argv(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"sha":"abc"}', stderr="")

    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    tr._gh_api("repos/o/r/contents/foo?ref=main", method="GET")
    assert captured == [["gh", "api", "--method", "GET", "repos/o/r/contents/foo?ref=main"]]


def test_gh_api_put_includes_input_dash(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        assert kwargs.get("input") == '{"x":1}'
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    tr._gh_api("repos/o/r/contents/foo", method="PUT", input_text='{"x":1}')
    assert captured == [
        ["gh", "api", "--method", "PUT", "repos/o/r/contents/foo", "--input", "-"],
    ]


def test_daily_freshness_same_et_calendar_day():
    et_day = datetime(2026, 11, 17, 10, 0, tzinfo=ET).date()
    # Retrieved yesterday 23:59 ET — not fresh today (prior bug used 24h sliding window)
    yesterday_late = datetime(2026, 11, 16, 23, 59, tzinfo=ET).astimezone(timezone.utc)
    assert not tr.is_cache_fresh_for_cadence(yesterday_late, et_day)
    # Retrieved today 00:01 ET — fresh
    today_early = datetime(2026, 11, 17, 0, 1, tzinfo=ET).astimezone(timezone.utc)
    assert tr.is_cache_fresh_for_cadence(today_early, et_day)


def test_weekly_freshness_from_monday(monkeypatch):
    monkeypatch.setenv("TORVIK_CADENCE", "weekly")
    # Wednesday Nov 4 2026; this week's Monday is Nov 2
    wed = datetime(2026, 11, 4, 12, 0, tzinfo=ET).date()
    sun_cache = datetime(2026, 11, 1, 15, 0, tzinfo=ET).astimezone(timezone.utc)
    assert not tr.is_cache_fresh_for_cadence(sun_cache, wed)
    mon_cache = datetime(2026, 11, 2, 8, 0, tzinfo=ET).astimezone(timezone.utc)
    assert tr.is_cache_fresh_for_cadence(mon_cache, wed)


def test_plan_partial_refresh_ratings_only(monkeypatch):
    monkeypatch.setenv("TORVIK_CADENCE", "daily")
    now = datetime(2026, 11, 17, 12, 0, tzinfo=ET).astimezone(timezone.utc)
    et_day = now.astimezone(ET).date()

    def fake_retrieved(repo, rel_path):
        if rel_path.endswith("ratings_latest.csv"):
            return datetime(2026, 11, 17, 6, 0, tzinfo=ET).astimezone(timezone.utc)
        if rel_path.endswith("usage_latest.json"):
            return datetime(2026, 11, 16, 6, 0, tzinfo=ET).astimezone(timezone.utc)
        return None

    monkeypatch.setattr(tr, "_committed_retrieved_at", fake_retrieved)
    plan = tr.plan_refresh("o/r", now=now)
    assert not plan.skip_all
    assert plan.fetch_ratings is False
    assert plan.fetch_usage is True
    assert "usage" in plan.reason


def test_plan_partial_refresh_usage_only(monkeypatch):
    monkeypatch.setenv("TORVIK_CADENCE", "daily")
    now = datetime(2026, 11, 17, 12, 0, tzinfo=ET).astimezone(timezone.utc)

    def fake_retrieved(repo, rel_path):
        if rel_path.endswith("ratings_latest.csv"):
            return datetime(2026, 11, 16, 6, 0, tzinfo=ET).astimezone(timezone.utc)
        if rel_path.endswith("usage_latest.json"):
            return datetime(2026, 11, 17, 6, 0, tzinfo=ET).astimezone(timezone.utc)
        return None

    monkeypatch.setattr(tr, "_committed_retrieved_at", fake_retrieved)
    plan = tr.plan_refresh("o/r", now=now)
    assert not plan.skip_all
    assert plan.fetch_ratings is True
    assert plan.fetch_usage is False


def test_plan_skip_when_both_fresh(monkeypatch):
    monkeypatch.setenv("TORVIK_CADENCE", "daily")
    now = datetime(2026, 11, 17, 12, 0, tzinfo=ET).astimezone(timezone.utc)
    fresh = datetime(2026, 11, 17, 6, 0, tzinfo=ET).astimezone(timezone.utc)

    monkeypatch.setattr(tr, "_committed_retrieved_at", lambda repo, rel: fresh)
    plan = tr.plan_refresh("o/r", now=now)
    assert plan.skip_all
    assert not plan.fetch_ratings and not plan.fetch_usage


def test_refresh_dry_run_partial_fetches_only_usage(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "test")
    now = datetime(2026, 11, 17, 12, 0, tzinfo=ET).astimezone(timezone.utc)

    monkeypatch.setattr(
        tr,
        "plan_refresh",
        lambda *a, **k: tr.RefreshPlan(False, "usage only", False, True),
    )

    def boom(*_a, **_k):
        raise AssertionError("network disabled")

    monkeypatch.setattr(tr, "_fetch_bytes", boom)
    assert tr.refresh(dry_run=True) == 0
    out = capsys.readouterr().out
    assert "getadvstats" in out
    assert "2027_team_results" not in out