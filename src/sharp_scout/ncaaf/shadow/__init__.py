"""Private NCAAF totals high-EV shadow tracking (not on GitHub Pages)."""

from sharp_scout.ncaaf.shadow.capture import record_from_pipeline
from sharp_scout.ncaaf.shadow.report import write_summary_and_report
from sharp_scout.ncaaf.shadow.settle import settle_shadow_ledger

__all__ = ["record_from_pipeline", "settle_shadow_ledger", "write_summary_and_report"]
