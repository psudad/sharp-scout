"""Unit tests for scripts/check_nfl_schedule_dedupe.py."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.check_nfl_schedule_dedupe as dedupe  # noqa: E402

SUN = "0 15 * * 0"
WEEKDAY = "0 15 * * 1-6"
MON = "0 16 * * 1"
THU_SUN = "0 22 * * 0,4"


class TestMostRecentSlot:
    def test_sunday_cron_on_sunday_after_slot(self):
        now = datetime(2026, 11, 15, 17, 0, tzinfo=timezone.utc)  # Sun
        slot = dedupe.most_recent_slot_utc(SUN, now)
        assert slot == datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)

    def test_sunday_cron_late_github_run(self):
        now = datetime(2026, 11, 15, 22, 30, tzinfo=timezone.utc)  # Sun, late for 15:00 slot
        slot = dedupe.most_recent_slot_utc(SUN, now)
        assert slot == datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)

    def test_weekday_range_monday(self):
        now = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)  # Mon
        slot = dedupe.most_recent_slot_utc(WEEKDAY, now)
        assert slot == datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)

    def test_weekday_range_sunday_no_match_walks_back(self):
        now = datetime(2026, 11, 15, 16, 0, tzinfo=timezone.utc)  # Sun — 1-6 does not match Sun
        slot = dedupe.most_recent_slot_utc(WEEKDAY, now)
        assert slot == datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)  # Sat

    def test_monday_only_cron(self):
        now = datetime(2026, 11, 17, 18, 0, tzinfo=timezone.utc)  # Tue
        slot = dedupe.most_recent_slot_utc(MON, now)
        assert slot == datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)  # Mon

    def test_thu_sun_cron_on_thursday(self):
        now = datetime(2026, 11, 19, 23, 0, tzinfo=timezone.utc)  # Thu
        slot = dedupe.most_recent_slot_utc(THU_SUN, now)
        assert slot == datetime(2026, 11, 19, 22, 0, tzinfo=timezone.utc)


class TestShouldSkip:
    NOW = datetime(2026, 11, 15, 17, 30, tzinfo=timezone.utc)

    def _run(self, *, created: str, event: str = "workflow_dispatch", run_id: int = 99, **kw):
        return {
            "id": run_id,
            "event": event,
            "created_at": created,
            "status": kw.get("status", "completed"),
            "conclusion": kw.get("conclusion", "success"),
        }

    def test_prior_dispatch_in_window_skips(self):
        runs = [self._run(created="2026-11-15T15:10:00Z")]
        with patch.object(dedupe, "fetch_workflow_runs", return_value=runs):
            skip, _ = dedupe.should_skip_scheduled_run(
                cron=SUN,
                now=self.NOW,
                current_run_id="12345",
                repo="o/r",
                token="t",
            )
        assert skip is True

    def test_run_outside_window_no_skip(self):
        runs = [self._run(created="2026-11-15T14:50:00Z")]  # before slot-5m (14:55)
        with patch.object(dedupe, "fetch_workflow_runs", return_value=runs):
            skip, _ = dedupe.should_skip_scheduled_run(
                cron=SUN,
                now=self.NOW,
                current_run_id="12345",
                repo="o/r",
                token="t",
            )
        assert skip is False

    def test_failed_prior_no_skip(self):
        runs = [self._run(created="2026-11-15T15:10:00Z", conclusion="failure")]
        with patch.object(dedupe, "fetch_workflow_runs", return_value=runs):
            skip, _ = dedupe.should_skip_scheduled_run(
                cron=SUN,
                now=self.NOW,
                current_run_id="12345",
                repo="o/r",
                token="t",
            )
        assert skip is False

    def test_cancelled_prior_no_skip(self):
        runs = [self._run(created="2026-11-15T15:10:00Z", conclusion="cancelled")]
        with patch.object(dedupe, "fetch_workflow_runs", return_value=runs):
            skip, _ = dedupe.should_skip_scheduled_run(
                cron=SUN,
                now=self.NOW,
                current_run_id="12345",
                repo="o/r",
                token="t",
            )
        assert skip is False

    def test_current_run_excluded(self):
        runs = [self._run(created="2026-11-15T15:10:00Z", run_id=12345)]
        with patch.object(dedupe, "fetch_workflow_runs", return_value=runs):
            skip, _ = dedupe.should_skip_scheduled_run(
                cron=SUN,
                now=self.NOW,
                current_run_id="12345",
                repo="o/r",
                token="t",
            )
        assert skip is False

    def test_in_progress_prior_skips(self):
        runs = [self._run(created="2026-11-15T15:10:00Z", status="in_progress", conclusion=None)]
        with patch.object(dedupe, "fetch_workflow_runs", return_value=runs):
            skip, _ = dedupe.should_skip_scheduled_run(
                cron=SUN,
                now=self.NOW,
                current_run_id="12345",
                repo="o/r",
                token="t",
            )
        assert skip is True

    def test_api_error_fail_open(self):
        with patch.object(
            dedupe,
            "fetch_workflow_runs",
            side_effect=urllib.error.HTTPError("url", 500, "err", {}, None),
        ):
            skip, why = dedupe.should_skip_scheduled_run(
                cron=SUN,
                now=self.NOW,
                current_run_id="12345",
                repo="o/r",
                token="t",
            )
        assert skip is False
        assert "fail open" in why.lower()

    def test_missing_token_fail_open(self):
        skip, _ = dedupe.should_skip_scheduled_run(
            cron=SUN,
            now=self.NOW,
            current_run_id="12345",
            repo="o/r",
            token=None,
        )
        assert skip is False


class TestMain:
    def test_non_schedule_never_skip(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
        dedupe.main()
        assert out.read_text().strip() == "skip=false"

    def test_schedule_with_prior_skip(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
        monkeypatch.setenv("GITHUB_SCHEDULE_CRON", SUN)
        monkeypatch.setenv("GITHUB_RUN_ID", "999")
        monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        fixed = datetime(2026, 11, 15, 17, 30, tzinfo=timezone.utc)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed if tz is None else fixed.astimezone(tz)

        monkeypatch.setattr(dedupe, "datetime", _FixedDatetime)
        with patch.object(
            dedupe,
            "fetch_workflow_runs",
            return_value=[
                {
                    "id": 1,
                    "event": "workflow_dispatch",
                    "created_at": "2026-11-15T15:10:00Z",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        ):
            dedupe.main()
        assert out.read_text().strip() == "skip=true"