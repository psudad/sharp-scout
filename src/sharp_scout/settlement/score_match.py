"""Match ledger plays to final score rows using canonical team names (no fuzzy guessing)."""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from sharp_scout.utils.odds import normalize_team
from sharp_scout.utils.slate import ET, parse_commence

logger = logging.getLogger(__name__)

# Plays and ESPN finals can disagree on kickoff by a few hours (tz, delays).
_DEFAULT_KICKOFF_WINDOW = timedelta(hours=40)
_AMBIGUOUS = "ambiguous"
_NO_MATCH = "no_match"


@dataclass(frozen=True)
class MatchResult:
    score: dict[str, Any] | None
    reason: str


def fold_accents(text: str) -> str:
    """Strip accents so 'San José' and 'San Jose' settle the same."""
    raw = text or ""
    folded = unicodedata.normalize("NFKD", raw)
    return folded.encode("ascii", "ignore").decode()


def normalize_for_settlement(name: str, *, sport: str) -> str:
    """Unicode fold + sport alias table (Odds API, ESPN, mascots)."""
    folded = fold_accents(name)
    return normalize_team(folded, sport)


def _kickoff_dt(row: dict[str, Any]) -> Any:
    return parse_commence(row.get("kickoff") or row.get("commence_time") or row.get("gameday"))


def _kickoff_date_key(row: dict[str, Any]) -> str | None:
    """Slate day in US/Eastern — matches ESPN scoreboard date fetch keys."""
    kick = _kickoff_dt(row)
    if kick is None:
        gd = row.get("gameday")
        return str(gd)[:10] if gd else None
    return kick.astimezone(ET).date().isoformat()


def _season_week_aligned(play: dict[str, Any], score: dict[str, Any]) -> bool:
    ps, pw = play.get("season"), play.get("week")
    ss, sw = score.get("season"), score.get("week")
    if ps is None or pw is None or ss is None or sw is None:
        return False
    return int(ps) == int(ss) and int(pw) == int(sw)


def _within_kickoff_window(play: dict[str, Any], score: dict[str, Any], *, window: timedelta) -> bool:
    pk, sk = _kickoff_dt(play), _kickoff_dt(score)
    if sk is None:
        if _season_week_aligned(play, score):
            return True
        if pk is not None:
            pd, sd = _kickoff_date_key(play), _kickoff_date_key(score)
            return bool(pd and sd and pd == sd)
        return False
    if pk is None:
        pd, sd = _kickoff_date_key(play), _kickoff_date_key(score)
        return bool(pd and sd and pd == sd)
    return abs((pk - sk).total_seconds()) <= window.total_seconds()


def _oriented_match(
    play: dict[str, Any],
    score: dict[str, Any],
    *,
    sport: str,
    allow_home_away_swap: bool,
) -> bool:
    """True when canonical away/home align.

    ``allow_home_away_swap`` may only be True for **totals** grading: the combined
    score is unchanged if venues are flipped. For spreads or moneyline, callers
    must pass ``allow_home_away_swap=False`` so ``home_score`` / ``away_score`` stay
    aligned with the play card.
    """
    pa = normalize_for_settlement(str(play.get("away_team") or ""), sport=sport)
    ph = normalize_for_settlement(str(play.get("home_team") or ""), sport=sport)
    sa = normalize_for_settlement(str(score.get("away_team") or ""), sport=sport)
    sh = normalize_for_settlement(str(score.get("home_team") or ""), sport=sport)
    if pa == sa and ph == sh:
        return True
    if allow_home_away_swap and pa == sh and ph == sa:
        return True
    return False


def _score_final(score: dict[str, Any]) -> bool:
    return score.get("home_score") is not None and score.get("away_score") is not None


def _event_index_keys(row: dict[str, Any]) -> list[str]:
    """Prefix ids by feed so Odds API hex and ESPN numerics never collide."""
    eid = str(row.get("event_id") or "").strip()
    keys: list[str] = []
    if eid:
        src = str(row.get("source") or "").lower()
        if src == "espn":
            keys.append(f"espn:{eid}")
        elif src in ("cfbfastr", "nflverse", "nflfastr"):
            gid = str(row.get("game_id") or eid).strip()
            keys.append(f"gid:{gid}")
        else:
            keys.append(f"odds:{eid}")
    gid = str(row.get("game_id") or "").strip()
    if gid:
        keys.append(f"gid:{gid}")
    return keys


def _play_event_lookup_keys(play: dict[str, Any]) -> list[str]:
    eid = str(play.get("event_id") or "").strip()
    if not eid:
        return []
    # Ledger plays use The Odds API ids unless explicitly tagged.
    src = str(play.get("event_id_source") or play.get("id_source") or "odds").lower()
    if src == "espn":
        return [f"espn:{eid}"]
    if eid.isdigit():
        return [f"espn:{eid}", f"odds:{eid}"]
    return [f"odds:{eid}"]


def build_score_index(
    scores: list[dict[str, Any]],
    *,
    sport: str,
) -> dict[str, list[dict[str, Any]]]:
    """Index finals by prefixed event_id and by canonical away@home (+ kickoff date)."""
    by_event: dict[str, dict[str, Any]] = {}
    by_pair: dict[str, list[dict[str, Any]]] = {}

    def _add_pair(key: str, row: dict[str, Any]) -> None:
        by_pair.setdefault(key, []).append(row)

    for raw in scores:
        if not _score_final(raw):
            continue
        row = dict(raw)
        away = normalize_for_settlement(str(row.get("away_team") or ""), sport=sport)
        home = normalize_for_settlement(str(row.get("home_team") or ""), sport=sport)
        row["away_team_norm"] = away
        row["home_team_norm"] = home

        for key in _event_index_keys(row):
            by_event[key] = row

        base = f"{away}@{home}"
        _add_pair(base, row)
        kdate = _kickoff_date_key(row)
        if kdate:
            _add_pair(f"{kdate}:{base}", row)
        season, week = row.get("season"), row.get("week")
        if season is not None:
            _add_pair(f"{season}:{base}", row)
            if week is not None:
                _add_pair(f"{season}:{week}:{base}", row)
                if kdate:
                    _add_pair(f"{season}:{week}:{kdate}:{base}", row)

        rev = f"{home}@{away}"
        _add_pair(rev, row)
        if kdate:
            _add_pair(f"{kdate}:{rev}", row)

    return {"by_event": by_event, "by_pair": by_pair}


def _filter_candidates(
    play: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    sport: str,
    kickoff_window: timedelta,
    allow_home_away_swap: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for score in candidates:
        if not _oriented_match(play, score, sport=sport, allow_home_away_swap=allow_home_away_swap):
            continue
        if not _within_kickoff_window(play, score, window=kickoff_window):
            continue
        out.append(score)
    return out


def match_play_to_score(
    play: dict[str, Any],
    index: dict[str, Any] | list[dict[str, Any]],
    *,
    sport: Literal["nfl", "ncaaf", "ncaam"] = "ncaaf",
    kickoff_window: timedelta = _DEFAULT_KICKOFF_WINDOW,
    allow_home_away_swap: bool = False,
) -> MatchResult:
    """
    Resolve a single final score row for a pending play.

    Prefer prefixed ``event_id`` when the ledger stores the same id as the score feed,
    but only after team or kickoff agreement. Otherwise match on canonical team names
    plus kickoff date/window. Multiple candidates → unsettled.
    """
    if isinstance(index, list):
        built = build_score_index(index, sport=sport)
    else:
        built = index

    by_event: dict[str, dict[str, Any]] = built.get("by_event") or {}
    by_pair: dict[str, list[dict[str, Any]]] = built.get("by_pair") or {}

    for key in _play_event_lookup_keys(play):
        hit = by_event.get(key)
        if hit and _score_final(hit):
            if _oriented_match(
                play, hit, sport=sport, allow_home_away_swap=allow_home_away_swap
            ) and _within_kickoff_window(play, hit, window=kickoff_window):
                return MatchResult(hit, "event_id")

    away = normalize_for_settlement(str(play.get("away_team") or ""), sport=sport)
    home = normalize_for_settlement(str(play.get("home_team") or ""), sport=sport)
    base = f"{away}@{home}"
    season, week = play.get("season"), play.get("week")

    rev = f"{home}@{away}"
    raw_pool: list[dict[str, Any]] = []
    seen_row: set[int] = set()
    for key in (base, rev):
        for row in by_pair.get(key) or []:
            oid = id(row)
            if oid in seen_row:
                continue
            seen_row.add(oid)
            raw_pool.append(row)

    if season is not None:
        raw_pool = [
            r
            for r in raw_pool
            if r.get("season") is None or int(r.get("season")) == int(season)
        ]
    if season is not None and week is not None:
        raw_pool = [
            r
            for r in raw_pool
            if r.get("week") is None or int(r.get("week")) == int(week)
        ]

    candidates = _filter_candidates(
        play,
        raw_pool,
        sport=sport,
        kickoff_window=kickoff_window,
        allow_home_away_swap=allow_home_away_swap,
    )

    if not candidates:
        return MatchResult(None, _NO_MATCH)

    if len(candidates) == 1:
        return MatchResult(candidates[0], "teams_kickoff")

    logger.warning(
        "Ambiguous settlement for play %s (%s@%s): %d candidate finals in kickoff window",
        play.get("id"),
        away,
        home,
        len(candidates),
    )
    return MatchResult(None, _AMBIGUOUS)
