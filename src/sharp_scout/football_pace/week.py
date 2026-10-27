"""Resolve current season/week from ESPN (free)."""

from __future__ import annotations

from datetime import datetime, timezone

from sharp_scout.data.espn_cfb import _fetch_scoreboard as fetch_cfb_sb


def current_season(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 8 else now.year - 1


def _nfl_week_from_event(event: dict) -> int | None:
    week_block = event.get("week")
    if week_block is None:
        return None
    try:
        return int(week_block.get("number") if isinstance(week_block, dict) else week_block)
    except (TypeError, ValueError):
        return None


def nfl_week_from_espn(season: int, *, now: datetime | None = None) -> int | None:
    now = now or datetime.now(timezone.utc)
    from datetime import timedelta

    from sharp_scout.data.espn_nfl import _fetch_scoreboard_raw

    candidates: list[tuple[int, int]] = []
    for delta in range(-3, 14):
        day = (now + timedelta(days=delta)).strftime("%Y%m%d")
        events = _fetch_scoreboard_raw({"dates": day, "limit": 100})
        for ev in events:
            w = _nfl_week_from_event(ev)
            if w is not None:
                candidates.append((delta, w))
    if candidates:
        # Prefer the nearest future (or today) slate over past weeks in the scan window.
        future = [c for c in candidates if c[0] >= 0]
        pick = min(future or candidates, key=lambda x: (x[0], x[1]))
        return pick[1]
    for w in range(1, 19):
        events = _fetch_scoreboard_raw({"year": season, "seasontype": 2, "week": w, "limit": 100})
        if not events:
            continue
        if any(
            ((ev.get("competitions") or [{}])[0].get("status") or {}).get("type", {}).get("state")
            != "post"
            for ev in events
        ):
            return w
    return None


def ncaaf_week_from_espn(season: int, *, now: datetime | None = None) -> int | None:
    now = now or datetime.now(timezone.utc)
    for delta in range(-3, 8):
        from datetime import timedelta

        day = (now + timedelta(days=delta)).strftime("%Y%m%d")
        rows = fetch_cfb_sb({"dates": day, "limit": 200})
        if rows and rows[0].get("week"):
            return int(rows[0]["week"])
    return None
