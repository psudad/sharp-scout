"""Power-conference map for the Sharp 3 / Sharp 3.5 mid-major rules.

Mid-major = any conference outside ACC, Big Ten, Big 12, SEC, Big East (the spec's
faithful equivalent of the original "Power 5" wording).
"""

from __future__ import annotations

# Action Network ``conference_type`` codes.
POWER_AN = frozenset({"ACC", "BIGTEN", "BIG12", "SEC", "BIGEAST"})
# ESPN men's college basketball conference (group) ids, used when AN has no code.
POWER_ESPN = frozenset({"2", "4", "7", "8", "23"})


def is_mid_major(*, an_conference: str | None = None, espn_conference_id: str | None = None) -> bool:
    code = (an_conference or "").strip().upper().replace(" ", "").replace("-", "")
    if code:
        return code not in POWER_AN
    cid = str(espn_conference_id or "").strip()
    if cid:
        return cid not in POWER_ESPN
    # Unknown conference: treat as mid-major (the looser 1.42 vig cap and road rule).
    return True
