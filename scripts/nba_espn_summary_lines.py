"""Parse NBA spread/total from ESPN summary pickcenter (backtest-only, free API)."""

from __future__ import annotations

import re
from typing import Any

from sharp_scout.data.espn_cfb import _get_json
from urllib.parse import urlencode

ESPN_SUMMARY_SITE = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
)
ESPN_SUMMARY_WEB = (
    "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
)


def _fetch_summary(event_id: str) -> dict[str, Any] | None:
    q = urlencode({"event": event_id})
    for base in (ESPN_SUMMARY_SITE, ESPN_SUMMARY_WEB):
        try:
            raw = _get_json(f"{base}?{q}")
        except Exception:
            continue
        if isinstance(raw, dict):
            return raw
    return None


def _parse_spread_line(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().lower().replace("−", "-")
    if not s:
        return None
    m = re.search(r"([+-]?\d+(?:\.\d+)?)", s)
    if not m:
        return None
    return float(m.group(1))


def _pick_primary_pickcenter(summary: dict[str, Any]) -> dict[str, Any] | None:
    pc = summary.get("pickcenter")
    if isinstance(pc, dict):
        return pc
    if not isinstance(pc, list) or not pc:
        return None
    # Prefer DraftKings / ESPN BET (priority 1)
    ranked = sorted(pc, key=lambda x: int((x.get("provider") or {}).get("priority") or 99))
    return ranked[0]


def lines_from_espn_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return consensus-like lines + metadata from summary pickcenter."""
    pick = _pick_primary_pickcenter(summary) or {}
    provider = (pick.get("provider") or {}).get("name") or "unknown"
    spread_home: float | None = None
    total: float | None = None
    line_kind = "close"

    ps = pick.get("pointSpread") or {}
    home_ps = (ps.get("home") or {}).get("close") or (ps.get("home") or {}).get("open") or {}
    away_ps = (ps.get("away") or {}).get("close") or (ps.get("away") or {}).get("open") or {}
    if home_ps.get("line") is not None:
        spread_home = _parse_spread_line(home_ps.get("line"))
    elif away_ps.get("line") is not None:
        away_line = _parse_spread_line(away_ps.get("line"))
        if away_line is not None:
            spread_home = -away_line

    if spread_home is None and pick.get("spread") is not None:
        mag = float(pick["spread"])
        home_odds = pick.get("homeTeamOdds") or {}
        away_odds = pick.get("awayTeamOdds") or {}
        if home_odds.get("favorite"):
            spread_home = -mag
        elif away_odds.get("favorite"):
            spread_home = mag
        else:
            # details like "BOS -1.5" — home positive if away favored
            spread_home = mag if "home" in str(pick.get("details") or "").lower() else -mag

    tot_block = pick.get("total") or {}
    over_close = (tot_block.get("over") or {}).get("close") or (tot_block.get("over") or {}).get("open") or {}
    if over_close.get("line"):
        total = _parse_spread_line(str(over_close.get("line")).replace("o", "").replace("O", ""))
    if total is None and pick.get("overUnder") is not None:
        total = float(pick["overUnder"])

    open_home_line = _parse_spread_line((ps.get("home") or {}).get("open", {}).get("line"))
    if open_home_line is None:
        away_open = _parse_spread_line((ps.get("away") or {}).get("open", {}).get("line"))
        if away_open is not None:
            open_home_line = -away_open
    open_total_line = None
    over_open = (tot_block.get("over") or {}).get("open") or {}
    if over_open.get("line"):
        open_total_line = _parse_spread_line(str(over_open.get("line")).replace("o", "").replace("O", ""))

    open_home = (ps.get("home") or {}).get("open") or {}
    open_total = (tot_block.get("over") or {}).get("open") or {}
    has_open = bool(open_home or open_total)

    return {
        "consensus_spread_home": spread_home,
        "consensus_total": total,
        "open_spread_home": open_home_line,
        "open_total": open_total_line,
        "provider": provider,
        "pickcenter_details": pick.get("details"),
        "line_timing": "close" if (ps.get("home") or {}).get("close") else ("open" if has_open else "unknown"),
        "caveat": (
            "ESPN summary pickcenter is typically closing (or open) lines from the listed "
            "sportsbook — not a walk-forward pre-tip Odds API snapshot."
        ),
    }


def fetch_espn_lines_for_event(event_id: str) -> dict[str, Any] | None:
    summary = _fetch_summary(event_id)
    if not summary:
        return None
    parsed = lines_from_espn_summary(summary)
    if parsed.get("consensus_spread_home") is None and parsed.get("consensus_total") is None:
        return None
    parsed["espn_event_id"] = event_id
    return parsed
