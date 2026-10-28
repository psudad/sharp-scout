"""Upcoming slate by calendar window (ESPN) merged with PBP lines."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.football_pace.games import PaceGame, load_ncaaf_games, load_nfl_games
from sharp_scout.utils.odds import normalize_team

ET = ZoneInfo("America/New_York")


def _parse_iso(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def kickoff_et_label(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    local = dt.astimezone(ET)
    return local.strftime("%a %b %d %Y %I:%M %p ET")


def default_projection_window(*, now: datetime | None = None) -> dict[str, tuple[date, date]]:
    """NCAAF Tue–Sat; NFL Thu–Mon (ET calendar days)."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ET).date()
    # Tue Oct 27 2026 case: anchor on today's ET date
    cfb_start = today
    # through upcoming Saturday (if today is Tue, +4 days to Sat)
    weekday = today.weekday()  # Mon=0
    days_to_sat = (5 - weekday) % 7
    if days_to_sat == 0 and today.weekday() != 5:
        days_to_sat = 7 if weekday > 5 else 0
    cfb_end = today + timedelta(days=max(days_to_sat, 0))
    if weekday <= 5 and days_to_sat == 0:
        cfb_end = today + timedelta(days=(5 - weekday))

    # NFL: next Thu through following Mon
    days_to_thu = (3 - weekday) % 7
    if days_to_thu == 0 and today.weekday() > 3:
        days_to_thu = 7
    nfl_start = today + timedelta(days=days_to_thu)
    nfl_end = nfl_start + timedelta(days=4)  # Thu..Mon
    return {
        "ncaaf": (cfb_start, cfb_end),
        "nfl": (nfl_start, nfl_end),
    }


def _dates_in_range(start: date, end: date) -> list[str]:
    out: list[str] = []
    d = start
    while d <= end:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def _espn_competition(event: dict[str, Any]) -> dict[str, Any] | None:
    comps = event.get("competitions") or []
    return comps[0] if comps else None


def _espn_lines(comp: dict[str, Any], *, home: str, away: str) -> tuple[float | None, float | None]:
    odds = comp.get("odds") or []
    if not odds:
        return None, None
    block = odds[0]
    total = block.get("overUnder")
    try:
        total_f = float(total) if total is not None else None
    except (TypeError, ValueError):
        total_f = None
    spread = block.get("spread")
    try:
        sp = float(spread) if spread is not None else None
    except (TypeError, ValueError):
        sp = None
    if sp is None:
        return None, total_f
    # ESPN `spread` magnitude is for the home team line (+ home dog)
    away_fav = (block.get("awayTeamOdds") or {}).get("favorite")
    if away_fav:
        spread_home = float(sp)
    else:
        spread_home = -float(sp)
    return spread_home, total_f


def parse_espn_event(event: dict[str, Any], *, sport: str) -> dict[str, Any] | None:
    comp = _espn_competition(event)
    if not comp:
        return None
    home = away = None
    for side in comp.get("competitors") or []:
        team = side.get("team") or {}
        code = normalize_team(
            str(team.get("abbreviation") or team.get("shortDisplayName") or team.get("displayName") or ""),
            sport,
        )
        if side.get("homeAway") == "home":
            home = code
        else:
            away = code
    if not home or not away:
        return None
    kick = _parse_iso(comp.get("date") or event.get("date"))
    status = ((comp.get("status") or {}).get("type") or {}).get("name") or ""
    state = ((comp.get("status") or {}).get("type") or {}).get("state") or ""
    spread_home, total_line = _espn_lines(comp, home=home, away=away)
    return {
        "event_id": str(event.get("id") or comp.get("id") or ""),
        "home": home,
        "away": away,
        "kickoff_utc": kick,
        "kickoff_et": kickoff_et_label(kick),
        "status": status,
        "state": state,
        "spread_home": spread_home,
        "total_line": total_line,
    }


def fetch_espn_events_by_dates(sport: str, ymd_dates: list[str]) -> list[dict[str, Any]]:
    if sport == "nfl":
        from sharp_scout.data.espn_nfl import _fetch_scoreboard_raw
    else:
        from sharp_scout.data.espn_cfb import _fetch_scoreboard_raw

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in ymd_dates:
        for ev in _fetch_scoreboard_raw({"dates": d, "limit": 400}):
            parsed = parse_espn_event(ev, sport=sport)
            if not parsed or parsed["event_id"] in seen:
                continue
            seen.add(parsed["event_id"])
            rows.append(parsed)
    return rows


def _index_pbp(games: list[PaceGame]) -> tuple[dict[str, PaceGame], dict[str, PaceGame]]:
    by_id: dict[str, PaceGame] = {}
    by_matchup: dict[str, PaceGame] = {}
    for g in games:
        by_id[str(g.game_id)] = g
        by_matchup[f"{g.away}@{g.home}"] = g
    return by_id, by_matchup


def merge_slate(
    sport: str,
    season: int,
    *,
    window: tuple[date, date],
) -> list[PaceGame]:
    from sharp_scout.football_pace.export import _enrich_ncaaf_teams

    ymd = _dates_in_range(window[0], window[1])
    espn = fetch_espn_events_by_dates(sport, ymd)
    if sport == "nfl":
        pbp = load_nfl_games([season])
    else:
        pbp = load_ncaaf_games([season], fbs_only=False)
        pbp = [g for g in pbp if g.spread_home is not None and g.total_line is not None]
        pbp = _enrich_ncaaf_teams(pbp, season, week=0)

    by_id, by_mu = _index_pbp(pbp)
    out: list[PaceGame] = []
    for ev in espn:
        if ev.get("state") == "post":
            continue
        kick = ev.get("kickoff_utc")
        if kick is not None:
            kd = kick.astimezone(ET).date()
            if kd < window[0] or kd > window[1]:
                continue
        g = by_id.get(ev["event_id"]) or by_mu.get(f"{ev['away']}@{ev['home']}")
        spread = ev.get("spread_home")
        total = ev.get("total_line")
        if g is None:
            if spread is None or total is None:
                continue
            kick_dt = kick.replace(tzinfo=None) if kick else None
            g = PaceGame(
                sport="ncaaf" if sport == "ncaaf" else "nfl",
                season=season,
                week=0,
                game_id=ev["event_id"],
                game_date=kick_dt,
                home=ev["home"],
                away=ev["away"],
                home_score=None,
                away_score=None,
                spread_home=spread,
                total_line=total,
            )
        else:
            if g.home in ("NAN", "nan", "") or g.away in ("NAN", "nan", ""):
                g = replace(g, home=ev["home"], away=ev["away"])
            if spread is not None and total is not None:
                g = replace(g, spread_home=spread, total_line=total, game_id=ev["event_id"])
        kick_dt = kick.replace(tzinfo=None) if kick else g.game_date
        g = replace(g, home=ev["home"], away=ev["away"], game_date=kick_dt)
        out.append(g)
    out.sort(key=lambda x: (x.game_date or datetime.min, x.away))
    return out
