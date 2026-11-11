"""Select near-tip closing lines from stored paper scans (no extra API)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.utils.kickoff import parse_kickoff_utc


def _window_bounds(kickoff: datetime) -> tuple[datetime, datetime]:
    settings = get_settings()
    pre = int(getattr(settings, "nba_pace_pre_tip_snapshot_minutes", 15))
    post = int(getattr(settings, "nba_pace_true_close_post_minutes", 5))
    return kickoff - timedelta(minutes=pre), kickoff + timedelta(minutes=post)


def select_true_close_scan(
    scans: list[dict[str, Any]],
    kickoff: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Last scan with ``at`` inside (T−pre, T+post]; returns (scan, captured_at iso)."""
    kick = parse_kickoff_utc(kickoff)
    if kick is None or not scans:
        return None, None
    start, end = _window_bounds(kick)
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for snap in scans:
        at = parse_kickoff_utc(snap.get("at"))
        if at is None:
            continue
        if start <= at <= end:
            candidates.append((at, snap))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[0])
    last_at, snap = candidates[-1]
    return dict(snap), last_at.isoformat()


def true_close_lines_for_game(g: dict[str, Any]) -> dict[str, Any] | None:
    """Consensus spread/total from the true-close scan, if any."""
    kick = g.get("kickoff")
    scans = g.get("scans") or []
    snap, captured_at = select_true_close_scan(scans, kick)
    if snap is None:
        return None
    lines = snap.get("lines") or {}
    out: dict[str, Any] = {
        "close_captured_at": captured_at,
        "close_spread_home_true": lines.get("consensus_spread_home"),
        "close_total_true": lines.get("consensus_total"),
        "close_pinnacle_spread_home_true": lines.get("pinnacle_spread_home"),
        "close_pinnacle_total_true": lines.get("pinnacle_total"),
    }
    if out.get("close_total_true") is None and out.get("close_spread_home_true") is None:
        return None
    return out


def game_missing_true_close_scan(g: dict[str, Any], *, now: datetime) -> bool:
    """True when ``now`` is inside this game's (T−pre, T+post] window and no close scan exists."""
    kick = parse_kickoff_utc(g.get("kickoff"))
    if kick is None:
        return False
    start, end = _window_bounds(kick)
    if now < start or now > end:
        return False
    snap, _ = select_true_close_scan(g.get("scans") or [], kick)
    return snap is None
