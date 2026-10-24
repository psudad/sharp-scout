"""Private on-disk locations for NCAAF high-EV totals shadow tracking."""

from __future__ import annotations

from pathlib import Path

from sharp_scout.config import DATA_DIR, ROOT

SHADOW_DIR = DATA_DIR / "shadow"
LEDGER_PATH = SHADOW_DIR / "ncaaf_totals_high_ev_ledger.json"
SUMMARY_PATH = SHADOW_DIR / "ncaaf_totals_high_ev_summary.json"
REPORTS_DIR = ROOT / "reports"
MARKDOWN_REPORT_PATH = REPORTS_DIR / "ncaaf_totals_high_ev.md"
