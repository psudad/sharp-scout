"""Torvik ↔ ESPN ↔ Odds API team name resolution.

Matching prefers an exact alias / canonical name (plus mechanical spelling
variants such as State/St. and A&M punctuation). Shorter names are never
allowed to swallow a longer school: "Texas" does not match
"Texas A&M-Corpus Christi", "California" does not match "Cal State Fullerton",
and "North Carolina" does not match "North Carolina State". Unknown or
ambiguous names return None rather than a fuzzy guess.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR

ALIASES_PATH = DATA_DIR / "ncaam" / "team_aliases.json"

# Tokens that are part of a school's identity, not a mascot. A leftover
# identity token means the shorter prefix is a different school.
_IDENTITY_TOKENS = frozenset(
    {
        "STATE",
        "ST",
        "TECH",
        "A",
        "M",
        "AM",
        "CC",
        "SOUTHERN",
        "NORTHERN",
        "EASTERN",
        "WESTERN",
        "INTERNATIONAL",
        "CHRISTIAN",
        "BAPTIST",
        "WESLEYAN",
        "LUTHERAN",
        "CORPUS",
        "CHRISTI",
        "KINGSVILLE",
        "COMMERCE",
        "UPSTATE",
        "CITY",
        "COLLEGE",
        "UNIVERSITY",
        "CAMPUS",
        "CENTRAL",
        "POLY",
        "FULLERTON",
        "NORTHRIDGE",
        "BAKERSFIELD",
        "MARCOS",
        "VALLEY",
        "A&T",
        "T",  # A&T -> A T
    }
)


def _norm_key(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", (s or "").upper())
    return re.sub(r"\s+", " ", s).strip()


def _variant_keys(raw: str) -> list[str]:
    """Exact-lookup keys, including State/St. and N.C./NC mechanical variants."""
    key = _norm_key(raw)
    if not key:
        return []
    keys = [key]
    if key.endswith(" STATE"):
        keys.append(key[: -len(" STATE")] + " ST")
    if key.endswith(" ST"):
        keys.append(key[: -len(" ST")] + " STATE")
    # N.C. State is stored as "N C ST"; ESPN often uses "NC State" / "North Carolina State".
    if key.startswith("NC "):
        keys.append("N C " + key[3:])
    if key.startswith("N C "):
        keys.append("NC " + key[4:])
    if key == "NC STATE" or key == "N C STATE" or key == "NORTH CAROLINA STATE" or key == "NORTH CAROLINA ST":
        keys.extend(["N C ST", "N C STATE", "NC ST", "NC STATE", "NORTH CAROLINA ST", "NORTH CAROLINA STATE"])
    return list(dict.fromkeys(k for k in keys if k))


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


def _lookup_exact(raw: str, aliases: dict[str, str], canon: frozenset[str]) -> str | None:
    for key in _variant_keys(raw):
        hit = aliases.get(key)
        if hit:
            return hit
    # Direct canonical name (already normalized spelling).
    raw_key = _norm_key(raw)
    for name in canon:
        if _norm_key(name) == raw_key:
            return name
        if raw_key in _variant_keys(name):
            return name
    return None


def normalize_ncaam(name: str) -> str | None:
    """Map a display/Odds API/ESPN name to a Torvik canonical team, or None if unknown.

    Exact id/alias matching only, plus mechanical spelling variants and a unique
    *expansion* (e.g. "Grambling" -> "Grambling St."). Never contracts a longer
    school name down to a shorter one.
    """
    raw = (name or "").strip()
    if not raw:
        return None
    aliases = _alias_map()
    canon = torvik_teams()
    hit = _lookup_exact(raw, aliases, canon)
    if hit:
        return hit

    # Strip a trailing mascot ("Texas Longhorns") only when every leftover
    # token is not a school-identity word and the remainder is an exact match.
    parts = raw.split()
    if len(parts) >= 2:
        remainder = " ".join(parts[:-1])
        last_tokens = _norm_key(parts[-1]).split()
        # "A&M-Kingsville" is one whitespace token but contains identity words.
        if last_tokens and not any(tok in _IDENTITY_TOKENS for tok in last_tokens):
            hit = _lookup_exact(remainder, aliases, canon)
            # Remainder must itself be that school (exact or State/St. variant),
            # not a unique-expansion of a different name.
            if hit and (
                _norm_key(hit) == _norm_key(remainder)
                or _norm_key(remainder) in set(_variant_keys(hit))
            ):
                return hit

    # Unique expansion: query is a proper prefix of exactly one canonical (or alias target).
    # "Grambling" -> "Grambling St."  — not "Texas A&M-CC" -> "Texas".
    key = _norm_key(raw)
    if key and canon:
        hits = [t for t in canon if _norm_key(t) == key or _norm_key(t).startswith(key + " ")]
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
