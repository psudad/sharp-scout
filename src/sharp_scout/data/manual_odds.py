"""Load manually pasted odds slates (preseason / when The Odds API has no feed)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.utils.odds import normalize_team


def _parse_commence(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def normalize_manual_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one game from a manual slate JSON file."""
    home = normalize_team(str(raw.get("home_team") or raw.get("home") or ""))
    away = normalize_team(str(raw.get("away_team") or raw.get("away") or ""))
    if not home or not away:
        raise ValueError(f"manual event missing home/away teams: {raw}")

    bookmakers: dict[str, Any] = {}
    for key, bm in (raw.get("bookmakers") or {}).items():
        markets: dict[str, Any] = {}
        for mkey, outcomes in (bm.get("markets") or {}).items():
            norm_outcomes = []
            for o in outcomes or []:
                side = o.get("side")
                if not side and mkey == "spreads":
                    team = normalize_team(str(o.get("name") or o.get("team") or ""))
                    side = "home" if team == home else "away"
                elif not side and mkey == "h2h":
                    team = normalize_team(str(o.get("name") or ""))
                    side = "home" if team == home else "away"
                elif not side and mkey == "totals":
                    side = str(o.get("name") or o.get("side") or "").lower()
                norm_outcomes.append(
                    {
                        "side": side,
                        "name": o.get("name"),
                        "price": o.get("price"),
                        "point": o.get("point"),
                    }
                )
            markets[mkey] = norm_outcomes
        bookmakers[str(key).lower()] = {
            "key": str(key).lower(),
            "title": bm.get("title") or str(key),
            "is_sharp": bool(bm.get("is_sharp")),
            "markets": markets,
        }

    event_id = raw.get("event_id") or f"manual-{away}-{home}"
    return {
        "event_id": event_id,
        "sport_key": "americanfootball_nfl",
        "commence_time": _parse_commence(raw.get("commence_time")),
        "home_team": home,
        "away_team": away,
        "home_team_raw": raw.get("home_team_raw") or home,
        "away_team_raw": raw.get("away_team_raw") or away,
        "bookmakers": bookmakers,
        "captured_at": datetime.now(timezone.utc),
        "source": "manual",
    }


def load_manual_slate(path: str | Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load manual slate JSON. Returns (events, an_date YYYYMMDD or None)."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, list):
        events_raw = data
        an_date = None
    elif isinstance(data, dict):
        events_raw = data.get("games") or data.get("events") or []
        an_date = data.get("an_date") or data.get("date")
    else:
        raise ValueError("manual slate must be a JSON object with games[] or a list of games")
    events = [normalize_manual_event(ev) for ev in events_raw]
    if not events:
        raise ValueError("manual slate has no games")
    return events, str(an_date) if an_date else None
