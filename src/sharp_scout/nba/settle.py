"""Grade NBA shadow ledger plays from ESPN final scores + box scores."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.data.espn_nba import fetch_espn_nba_box_scores, fetch_espn_nba_scores
from sharp_scout.ledger.tracker import settle_play
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.clv import recompute_nba_clv_summary_fields, sanitize_play_clv
from sharp_scout.nba.ledger import is_demo_nba_row, load_nba_ledger, save_nba_ledger
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.kickoff import kickoff_in_horizon, parse_kickoff_utc

logger = logging.getLogger(__name__)

_OPEN = frozenset({"paper", "pending", None, ""})


def _norm_team(name: Any) -> str:
    return normalize_nba_team(str(name or ""))


def _kickoff_eligible(row: dict[str, Any], *, now: datetime) -> bool:
    kick = parse_kickoff_utc(row.get("kickoff"))
    if kick is None:
        return True
    # NBA games ~2.5h; grade after kickoff + 2.5h buffer.
    return kick <= now - timedelta(hours=2, minutes=30)


def void_plays_outside_horizon(
    ledger: dict[str, Any],
    *,
    horizon_hours: float | None = None,
    now: datetime | None = None,
) -> int:
    """Mark paper plays logged for games far outside the scan window (no delete)."""
    settings = get_settings()
    hours = horizon_hours if horizon_hours is not None else settings.nba_prop_horizon_hours
    now = now or datetime.now(timezone.utc)
    voided = 0
    for play in ledger.get("plays") or []:
        if is_demo_nba_row(play):
            continue
        if str(play.get("status") or "").lower() not in _OPEN:
            continue
        created = parse_kickoff_utc(play.get("created_at"))
        kick = parse_kickoff_utc(play.get("kickoff"))
        if kick is None or created is None:
            continue
        # Void if kickoff was more than horizon after the play was logged.
        if kick > created + timedelta(hours=hours + 1):
            play["status"] = "void"
            play["exclude_reason"] = "kickoff_outside_horizon"
            play["pnl_units"] = 0.0
            play["settled_at"] = datetime.now(timezone.utc).isoformat()
            sanitize_play_clv(play, reason="kickoff_outside_horizon")
            voided += 1
        elif not kickoff_in_horizon(play.get("kickoff"), hours, now=created):
            # Logged when kickoff was already outside the forward window.
            play["status"] = "void"
            play["exclude_reason"] = "kickoff_outside_horizon"
            play["pnl_units"] = 0.0
            play["settled_at"] = datetime.now(timezone.utc).isoformat()
            sanitize_play_clv(play, reason="kickoff_outside_horizon")
            voided += 1
    return voided


def _build_score_index(scores: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for g in scores:
        away = _norm_team(g.get("away_team"))
        home = _norm_team(g.get("home_team"))
        row = {**g, "away_team": away, "home_team": home}
        base = f"{away}@{home}"
        index[base] = row
        if g.get("event_id"):
            index[str(g["event_id"])] = row
    return index


def _lookup_play(play: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    eid = play.get("event_id")
    if eid and str(eid) in index:
        return index[str(eid)]
    away = _norm_team(play.get("away_team"))
    home = _norm_team(play.get("home_team"))
    return index.get(f"{away}@{home}")


def _prop_value(
    play: dict[str, Any],
    box_by_event: dict[str, dict[str, dict[str, float]]],
    game: dict[str, Any],
) -> float | None:
    market = str(play.get("market") or "")
    name = str(play.get("player_name") or "").strip().lower()
    if not name or not market.startswith("player_"):
        return None
    eid = str(game.get("event_id") or play.get("event_id") or "")
    players = box_by_event.get(eid) or {}
    stats = players.get(name)
    if stats is None:
        # Fuzzy: last name match when unique
        parts = name.split()
        if parts:
            last = parts[-1]
            hits = [v for k, v in players.items() if last in k]
            if len(hits) == 1:
                stats = hits[0]
    if not stats:
        return None
    return stats.get(market)


def settle_nba_ledger(
    ledger: dict[str, Any] | None = None,
    *,
    scores: list[dict[str, Any]] | None = None,
    path: Any = None,
) -> dict[str, Any]:
    """Settle open NBA paper plays; returns updated ledger."""
    ledger = ledger if ledger is not None else load_nba_ledger(path)
    now = datetime.now(timezone.utc)
    void_plays_outside_horizon(ledger, now=now)

    scores = scores if scores is not None else fetch_espn_nba_scores()
    index = _build_score_index(scores)

    pending = [
        p
        for p in ledger.get("plays") or []
        if str(p.get("status") or "").lower() in _OPEN
        and not is_demo_nba_row(p)
        and _kickoff_eligible(p, now=now)
    ]
    event_ids = []
    for p in pending:
        g = _lookup_play(p, index)
        if g and g.get("event_id"):
            event_ids.append(str(g["event_id"]))
    box_by_event = fetch_espn_nba_box_scores(sorted(set(event_ids))) if event_ids else {}

    settled = 0
    for play in pending:
        if str(play.get("status") or "").lower() not in _OPEN:
            continue
        g = _lookup_play(play, index)
        if not g or g.get("home_score") is None or g.get("away_score") is None:
            continue
        hs, as_ = int(g["home_score"]), int(g["away_score"])
        is_prop = (play.get("play_type") == "prop") or str(play.get("market") or "").startswith("player_")
        if is_prop:
            val = _prop_value(play, box_by_event, g)
            if val is None:
                continue
            settle_play(play, hs, as_, prop_value=val)
        else:
            settle_play(play, hs, as_)
        settled += 1

    recompute_nba_clv_summary_fields(ledger)
    save_nba_ledger(ledger, path or nba_paths.NBA_LEDGER_PATH)
    logger.info("NBA ledger: settled %d plays", settled)
    return ledger
