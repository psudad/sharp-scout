"""Slate windows — college football week (Mon–Sun ET) and kickoff filters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_commence(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _as_utc(raw)
    if isinstance(raw, str) and raw:
        try:
            return _as_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def filter_plays_nfl_week(
    plays: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Keep ledger plays whose kickoff falls in the current NFL week (Wed–Tue ET)."""
    start, end = nfl_week_bounds(now)
    out: list[dict[str, Any]] = []
    for play in plays:
        kickoff = parse_commence(play.get("kickoff") or play.get("commence_time"))
        if kickoff is None:
            continue
        if start <= kickoff <= end:
            out.append(play)
    return out


def filter_events_nfl_week(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Keep events whose kickoff falls in the current NFL week (Wed–Tue ET)."""
    start, end = nfl_week_bounds(now)
    out: list[dict[str, Any]] = []
    for ev in events:
        kickoff = parse_commence(ev.get("commence_time"))
        if kickoff is None:
            continue
        if start <= kickoff <= end:
            out.append(ev)
    return out


def filter_events_nfl_display_slate(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Games tab: current NFL week, or the next week with scheduled kickoffs."""
    now = _as_utc(now or datetime.now(timezone.utc))
    current = filter_events_nfl_week(events, now=now)
    if current:
        return current
    upcoming: list[dict[str, Any]] = []
    for ev in events:
        kickoff = parse_commence(ev.get("commence_time"))
        if kickoff is not None and kickoff >= now - timedelta(minutes=15):
            upcoming.append(ev)
    if not upcoming:
        return []
    upcoming.sort(key=lambda e: parse_commence(e.get("commence_time")) or now)
    anchor = parse_commence(upcoming[0].get("commence_time"))
    if anchor is None:
        return []
    start, end = nfl_week_bounds(anchor)
    return [
        ev
        for ev in events
        if (kickoff := parse_commence(ev.get("commence_time"))) is not None and start <= kickoff <= end
    ]


def nfl_week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return UTC bounds for the NFL betting week containing ``now``.

    Week = Wednesday 00:00 America/New_York through the following Tuesday 23:59:59 ET.
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    local = now.astimezone(ET)
    days_since_wednesday = (local.weekday() - 2) % 7
    week_start_local = (local - timedelta(days=days_since_wednesday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)
    return week_start_local.astimezone(timezone.utc), week_end_local.astimezone(timezone.utc)


def college_week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return UTC bounds for the college football week containing ``now``.

    Week = Monday 00:00 America/New_York through the following Sunday 23:59:59 ET.
    Aligns with typical Monday opening lines for the weekend slate.
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    local = now.astimezone(ET)
    days_since_monday = local.weekday()  # Monday = 0
    week_start_local = (local - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)
    return week_start_local.astimezone(timezone.utc), week_end_local.astimezone(timezone.utc)


def following_college_week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Bounds for the college week immediately after the one containing ``now``."""
    _start, end = college_week_bounds(now)
    return college_week_bounds(end + timedelta(hours=1))


def filter_events_college_week(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    include_started: bool = False,
) -> list[dict[str, Any]]:
    """Keep events whose kickoff falls in the current college week (ET Mon–Sun)."""
    start, end = college_week_bounds(now)
    now = _as_utc(now or datetime.now(timezone.utc))
    out: list[dict[str, Any]] = []
    for ev in events:
        kickoff = parse_commence(ev.get("commence_time"))
        if kickoff is None:
            continue
        if kickoff < start or kickoff > end:
            continue
        if not include_started and kickoff < now - timedelta(minutes=15):
            continue
        out.append(ev)
    return out


def filter_events_in_college_week(
    events: list[dict[str, Any]],
    week_start: datetime,
    week_end: datetime,
    *,
    now: datetime | None = None,
    include_started: bool = False,
) -> list[dict[str, Any]]:
    """Keep events whose kickoff falls in an explicit college week window."""
    now = _as_utc(now or datetime.now(timezone.utc))
    out: list[dict[str, Any]] = []
    for ev in events:
        kickoff = parse_commence(ev.get("commence_time"))
        if kickoff is None:
            continue
        if kickoff < week_start or kickoff > week_end:
            continue
        if not include_started and kickoff < now - timedelta(minutes=15):
            continue
        out.append(ev)
    return out


def filter_plays_college_week(
    plays: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Keep ledger plays whose kickoff falls in the current college week."""
    start, end = college_week_bounds(now)
    out: list[dict[str, Any]] = []
    for play in plays:
        kickoff = parse_commence(play.get("kickoff") or play.get("commence_time"))
        if kickoff is None:
            continue
        if start <= kickoff <= end:
            out.append(play)
    return out


def college_week_label(week_start: datetime) -> str:
    """Human label for a college week (Mon–Sun ET)."""
    start_et = _as_utc(week_start).astimezone(ET)
    end_et = (start_et + timedelta(days=6)).replace(hour=23, minute=59)
    if start_et.year == end_et.year:
        return f"{start_et.strftime('%b %d')} – {end_et.strftime('%b %d, %Y')}"
    return f"{start_et.strftime('%b %d, %Y')} – {end_et.strftime('%b %d, %Y')}"


def filter_stage_cards_current_slate(
    cards: list[dict[str, Any]],
    *,
    games: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Keep stage cards that belong to the current pipeline games list."""
    if not games:
        return cards
    ids = {str(g.get("event_id")) for g in games if g.get("event_id")}
    if not ids:
        return cards
    return [c for c in cards if str(c.get("event_id") or "") in ids]


def stage_card_college_week_start(card: dict[str, Any]) -> datetime | None:
    """Monday ET week start for a stage card's kickoff."""
    kickoff = parse_commence(
        card.get("kickoff") or card.get("commence_time") or card.get("created_at")
    )
    if kickoff is None:
        return None
    start, _end = college_week_bounds(kickoff)
    return start


def partition_stage_cards_current_historical(
    cards: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[datetime, list[dict[str, Any]]]]]:
    """Split stage cards into this college week vs prior weeks (newest first)."""
    current_start, _current_end = college_week_bounds(now)
    current_key = current_start.isoformat()
    current: list[dict[str, Any]] = []
    historical: dict[str, list[dict[str, Any]]] = {}
    hist_starts: dict[str, datetime] = {}
    for card in cards:
        week_start = stage_card_college_week_start(card)
        if week_start is None:
            continue
        key = week_start.isoformat()
        if key == current_key:
            current.append(card)
        else:
            historical.setdefault(key, []).append(card)
            hist_starts[key] = week_start
    ordered = sorted(hist_starts.keys(), reverse=True)
    return current, [(hist_starts[k], historical[k]) for k in ordered]


def group_stage_cards_by_college_week(
    cards: list[dict[str, Any]],
) -> list[tuple[datetime, list[dict[str, Any]]]]:
    """Group stage cards by college week; newest weeks first."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    starts: dict[str, datetime] = {}
    for card in cards:
        kickoff = parse_commence(
            card.get("kickoff") or card.get("commence_time") or card.get("created_at")
        )
        if kickoff is None:
            continue
        start, _end = college_week_bounds(kickoff)
        key = start.isoformat()
        buckets.setdefault(key, []).append(card)
        starts[key] = start
    ordered = sorted(starts.keys(), reverse=True)
    return [(starts[k], buckets[k]) for k in ordered]
