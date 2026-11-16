"""Critical input feed health — machine-readable status for CI and operators."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR, get_settings

logger = logging.getLogger(__name__)

FEEDS_PATH = DATA_DIR / "health" / "feeds.json"


class FeedStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    MISSING = "missing"


@dataclass
class FeedSnapshot:
    id: str
    status: FeedStatus
    reason: str
    last_success_at: str | None = None
    last_checked_at: str | None = None
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return {k: v for k, v in d.items() if v is not None}


class FeedHealthRegistry:
    def __init__(self) -> None:
        self._feeds: dict[str, FeedSnapshot] = {}
        self._checked_at: str | None = None

    def update(
        self,
        feed_id: str,
        *,
        status: FeedStatus,
        reason: str,
        last_success_at: datetime | str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        when = datetime.now(timezone.utc).isoformat()
        ok_at = last_success_at
        if isinstance(ok_at, datetime):
            ok_at = ok_at.astimezone(timezone.utc).isoformat()
        snap = FeedSnapshot(
            id=feed_id,
            status=status,
            reason=reason,
            last_success_at=ok_at if status == FeedStatus.OK else None,
            last_checked_at=when,
            detail=detail,
        )
        self._feeds[feed_id] = snap
        self._checked_at = when
        level = logging.INFO
        if status == FeedStatus.MISSING:
            level = logging.ERROR
            logger.error("FEED_HEALTH %s: %s — %s", feed_id, status.value, reason)
        elif status == FeedStatus.DEGRADED:
            level = logging.WARNING
            logger.warning("FEED_HEALTH %s: %s — %s", feed_id, status.value, reason)
        else:
            logger.log(level, "FEED_HEALTH %s: ok — %s", feed_id, reason)

    def merge_prior(self, prior: dict[str, Any]) -> None:
        for row in prior.get("feeds") or []:
            fid = row.get("id")
            if not fid or fid in self._feeds:
                continue
            try:
                st = FeedStatus(str(row.get("status") or "missing"))
            except ValueError:
                st = FeedStatus.MISSING
            self._feeds[fid] = FeedSnapshot(
                id=fid,
                status=st,
                reason=str(row.get("reason") or ""),
                last_success_at=row.get("last_success_at"),
                last_checked_at=row.get("last_checked_at"),
                detail=row.get("detail"),
            )

    def payload(self, *, context: str | None = None) -> dict[str, Any]:
        return {
            "generated_at": self._checked_at or datetime.now(timezone.utc).isoformat(),
            "context": context,
            "feeds": [self._feeds[k].to_dict() for k in sorted(self._feeds)],
        }

    def has_critical_missing(self, critical_ids: set[str]) -> bool:
        for fid in critical_ids:
            snap = self._feeds.get(fid)
            if snap is None or snap.status == FeedStatus.MISSING:
                return True
        return False


def load_feeds_file(path: Path | None = None) -> dict[str, Any]:
    path = path or FEEDS_PATH
    try:
        return json.loads(path.read_text())
    except OSError:
        return {}
    except json.JSONDecodeError:
        return {}


def write_feeds_file(
    registry: FeedHealthRegistry,
    *,
    path: Path | None = None,
    context: str | None = None,
) -> Path:
    path = path or FEEDS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    prior = load_feeds_file(path)
    registry.merge_prior(prior)
    # Preserve last_success_at from prior when a feed was not touched this run.
    for row in prior.get("feeds") or []:
        fid = row.get("id")
        snap = registry._feeds.get(fid)
        if not fid or not snap:
            continue
        if snap.status != FeedStatus.OK and row.get("last_success_at") and not snap.last_success_at:
            snap.last_success_at = row.get("last_success_at")
    payload = registry.payload(context=context)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def record_action_network_splits(
    registry: FeedHealthRegistry,
    *,
    sport: str,
    splits: list[dict[str, Any]],
    events: list[dict[str, Any]] | None,
    auth_configured: bool,
) -> None:
    feed_id = f"action_network_splits_{sport}"
    n = len(splits)
    if n == 0:
        registry.update(
            feed_id,
            status=FeedStatus.MISSING,
            reason="Action Network returned no games for this slate",
            detail={"auth_configured": auth_configured, "n_games": 0},
        )
        return
    with_money = sum(
        1
        for g in splits
        for m in (g.get("markets") or {}).values()
        if isinstance(m, dict) and (m.get("home_money_pct") is not None or m.get("over_money_pct") is not None)
    )
    if with_money == 0 and auth_configured:
        registry.update(
            feed_id,
            status=FeedStatus.DEGRADED,
            reason="Splits rows present but money % missing (auth or AN outage)",
            last_success_at=datetime.now(timezone.utc),
            detail={"n_games": n, "with_money_rows": 0},
        )
        return
    if events:
        from sharp_scout.phase4.filters import _find_split_game

        matched = sum(
            1
            for ev in events
            if _find_split_game(splits, ev["home_team"], ev["away_team"], sport=sport) is not None
        )
        pct = matched / max(len(events), 1)
        if pct < 0.5:
            registry.update(
                feed_id,
                status=FeedStatus.DEGRADED,
                reason=f"Only {matched}/{len(events)} slate games matched AN rows",
                last_success_at=datetime.now(timezone.utc),
                detail={"matched": matched, "slate": len(events), "n_splits": n},
            )
            return
        if matched < len(events):
            registry.update(
                feed_id,
                status=FeedStatus.DEGRADED,
                reason=f"AN splits partial match {matched}/{len(events)}",
                last_success_at=datetime.now(timezone.utc),
                detail={"matched": matched, "slate": len(events)},
            )
            return
    registry.update(
        feed_id,
        status=FeedStatus.OK,
        reason=f"{n} games, money/ticket present" if with_money else f"{n} games (ticket-only)",
        last_success_at=datetime.now(timezone.utc),
        detail={"n_games": n, "with_money_rows": with_money},
    )


def record_odds_api(
    registry: FeedHealthRegistry,
    *,
    sport: str,
    n_events: int,
    demo: bool = False,
) -> None:
    feed_id = f"odds_api_{sport}"
    if demo:
        registry.update(
            feed_id,
            status=FeedStatus.DEGRADED,
            reason="demo odds (not live Odds API)",
            detail={"n_events": n_events},
        )
        return
    if n_events <= 0:
        registry.update(feed_id, status=FeedStatus.MISSING, reason="Odds API returned no events")
        return
    registry.update(
        feed_id,
        status=FeedStatus.OK,
        reason=f"{n_events} events",
        last_success_at=datetime.now(timezone.utc),
        detail={"n_events": n_events},
    )


def record_torvik_ratings(registry: FeedHealthRegistry, *, ok: bool, reason: str, cache_date: str | None = None) -> None:
    if ok:
        registry.update(
            "torvik_ratings",
            status=FeedStatus.OK,
            reason=reason,
            last_success_at=datetime.now(timezone.utc),
            detail={"cache_date_et": cache_date},
        )
    else:
        registry.update("torvik_ratings", status=FeedStatus.MISSING, reason=reason)


def critical_feed_ids_for_sport(sport: str) -> set[str]:
    sport = sport.lower()
    base = {f"odds_api_{sport}", f"action_network_splits_{sport}"}
    if sport == "ncaam":
        base.add("torvik_ratings")
    return base


def evaluate_registry_for_ci(registry: FeedHealthRegistry, *, sport: str) -> int:
    """Return 0 if healthy, 1 if any critical feed missing."""
    critical = critical_feed_ids_for_sport(sport)
    if registry.has_critical_missing(critical):
        return 1
    return 0