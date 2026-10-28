"""CLV and model error for Pace paper (stored lines only — no new Odds API)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sharp_scout.utils.kickoff import parse_kickoff_utc


def last_pre_tip_scan(scans: list[dict[str, Any]], *, kickoff: Any) -> dict[str, Any] | None:
    kick = parse_kickoff_utc(kickoff)
    if kick is None:
        return scans[-1] if scans else None
    pre = [s for s in scans if not s.get("after_tip")]
    if not pre:
        pre = [s for s in scans if parse_kickoff_utc(s.get("at")) and parse_kickoff_utc(s.get("at")) <= kick]
    return pre[-1] if pre else (scans[-1] if scans else None)


def pace_clv_fields(
    *,
    pick: dict[str, Any],
    pre_tip: dict[str, Any],
    close_spread_home: float | None,
    close_total: float | None,
    proj_margin: float,
    proj_total: float,
) -> dict[str, Any]:
    """CLV vs last stored pre-tip line; model error vs closing line."""
    lines_open = pre_tip.get("lines") or {}
    out: dict[str, Any] = {
        "open_spread_home": lines_open.get("consensus_spread_home"),
        "open_total": lines_open.get("consensus_total"),
        "close_spread_home": close_spread_home,
        "close_total": close_total,
        "clv_toward_model": None,
        "model_error_vs_close": None,
    }
    if pick.get("kind") == "spread" and close_spread_home is not None:
        open_cs = lines_open.get("consensus_spread_home")
        if open_cs is not None:
            move = float(close_spread_home) - float(open_cs)
            edge_open = proj_margin + float(open_cs)
            out["clv_toward_model"] = (move > 0 and edge_open > 0) or (move < 0 and edge_open < 0)
        out["model_error_vs_close"] = round(proj_margin + float(close_spread_home), 2)
    elif pick.get("kind") == "total" and close_total is not None:
        open_ct = lines_open.get("consensus_total")
        if open_ct is not None:
            move = float(close_total) - float(open_ct)
            edge_open = proj_total - float(open_ct)
            out["clv_toward_model"] = (move > 0 and edge_open > 0) or (move < 0 and edge_open < 0)
        out["model_error_vs_close"] = round(proj_total - float(close_total), 2)
    return out
