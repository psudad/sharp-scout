"""Stake rules for the unlisted Sharp 3 / Sharp 3.5 lab.

Does not apply to the public NCAAM 1u board or the NBA model.
"""

from __future__ import annotations

# Jason-approved maximum per lab ticket (2026-11-14). Relative sizing below
# this cap is unchanged; tickets that would have been 5–10u are clipped to the cap.
LAB_MAX_STAKE_UNITS = 4.0


def cap_lab_stake(units: float) -> float:
    """Clip a lab stake to LAB_MAX_STAKE_UNITS. Already-locked ledger rows are not rewritten."""
    return round(min(float(units), LAB_MAX_STAKE_UNITS), 1)
