"""Torvik ↔ ESPN ↔ Odds API team name resolution."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR

ALIASES_PATH = DATA_DIR / "ncaam" / "team_aliases.json"


def _norm_key(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", (s or "").upper())
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def _alias_map() -> dict[str, str]:
    if not ALIASES_PATH.exists():
        return {}
    data = json.loads(ALIASES_PATH.read_text())
    return dict(data.get("aliases") or {})


@lru_cache(maxsize=1)
def torvik_teams() -> frozenset[str]:
    if not ALIASES_PATH.exists():
        return frozenset()
    data = json.loads(ALIASES_PATH.read_text())
    return frozenset(data.get("canonical") or [])


def normalize_ncaam(name: str) -> str | None:
    """Map a display/Odds API name to Torvik canonical team, or None if unknown."""
    raw = (name or "").strip()
    if not raw:
        return None
    aliases = _alias_map()
    hit = aliases.get(_norm_key(raw))
    if hit:
        return hit
    # Strip trailing mascot token when the first token(s) match a Torvik school.
    parts = raw.split()
    for n in range(len(parts), 0, -1):
        prefix = " ".join(parts[:n])
        hit = aliases.get(_norm_key(prefix))
        if hit:
            return hit
    if raw.endswith(" State"):
        hit = aliases.get(_norm_key(raw[:-6] + " St."))
        if hit:
            return hit
    # Unique prefix match against Torvik canon (e.g. "Grambling" -> "Grambling St.").
    canon = torvik_teams()
    if canon:
        key = _norm_key(raw)
        hits = [t for t in canon if _norm_key(t).startswith(key) or key.startswith(_norm_key(t))]
        if len(hits) == 1:
            return hits[0]
        hits = [t for t in canon if _norm_key(t.split()[0]) == key.split()[0]]
        if len(hits) == 1:
            return hits[0]
    return None


def register_ncaam_mascots(names: Any) -> None:
    """Extend alias map with mascot suffixes seen in Action Network payloads."""
    aliases = dict(_alias_map())
    changed = False
    for name in names:
        s = str(name or "").strip()
        if not s:
            continue
        canon = normalize_ncaam(s)
        if canon:
            key = _norm_key(s)
            if aliases.get(key) != canon:
                aliases[key] = canon
                changed = True
    if changed:
        ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(ALIASES_PATH.read_text()) if ALIASES_PATH.exists() else {"canonical": []}
        data["aliases"] = aliases
        ALIASES_PATH.write_text(json.dumps(data, indent=2) + "\n")
        _alias_map.cache_clear()


def slate_match_stats(espn_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Count how many ESPN competitor locations resolve to Torvik."""
    total = 0
    matched = 0
    unmatched: list[str] = []
    for ev in espn_events:
        for side in ("home", "away"):
            loc = ev.get(f"{side}_location") or ev.get(f"{side}_team") or ""
            total += 1
            if normalize_ncaam(str(loc)):
                matched += 1
            else:
                unmatched.append(str(loc))
    rate = (matched / total) if total else 1.0
    return {
        "total": total,
        "matched": matched,
        "rate": rate,
        "unmatched": sorted(set(unmatched)),
    }
