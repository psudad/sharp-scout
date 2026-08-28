"""NCAA football (FBS) pipeline — same 4-phase engine as NFL."""

from sharp_scout.ncaaf.pipeline import load_latest_ncaaf, run_ncaaf_pipeline

__all__ = ["load_latest_ncaaf", "run_ncaaf_pipeline"]