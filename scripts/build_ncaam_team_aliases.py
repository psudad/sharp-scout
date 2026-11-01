#!/usr/bin/env python3
"""Build data/ncaam/team_aliases.json from Torvik CSV + ESPN name variants."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR  # noqa: E402

TORVIK_URL = "https://barttorvik.com/2027_team_results.csv"
OUT = DATA_DIR / "ncaam" / "team_aliases.json"

# ESPN location strings that do not follow the State -> St. rule.
MANUAL: dict[str, str] = {
    "Grambling": "Grambling St.",
    "Hawai'i": "Hawaii",
    "Hawaii": "Hawaii",
    "IU Indianapolis": "IU Indy",
    "Long Island University": "LIU",
    "App State": "Appalachian St.",
    "FIU": "FIU",
    "Florida International": "FIU",
    "UMass": "Massachusetts",
    "UMass Lowell": "UMass Lowell",
    "UConn": "Connecticut",
    "UNC": "North Carolina",
    "UNLV": "UNLV",
    "USC": "USC",
    "UCLA": "UCLA",
    "UTEP": "UTEP",
    "UTSA": "UTSA",
    "VCU": "VCU",
    "SMU": "SMU",
    "TCU": "TCU",
    "BYU": "BYU",
    "LSU": "LSU",
    "Ole Miss": "Mississippi",
    "Pitt": "Pittsburgh",
    "Cal": "California",
    "Cal State": "Cal St.",
}


def _norm_key(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", s.upper())
    return re.sub(r"\s+", " ", s).strip()


def _variants(name: str) -> set[str]:
    out = {name, name.strip()}
    if name.endswith(" State"):
        out.add(name[:-6] + " St.")
    if name.endswith(" St."):
        out.add(name[:-4] + " State")
    return out


def main() -> int:
    torvik_path = DATA_DIR / "ncaam" / "ratings_latest.csv"
    if not torvik_path.exists():
        import httpx

        torvik_path.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(
            TORVIK_URL,
            headers={"User-Agent": "SharpScout/1.0 (github.com/psudad/sharp-scout; ratings cache)"},
            timeout=60.0,
        )
        r.raise_for_status()
        torvik_path.write_bytes(r.content)

    canon = [row["team"] for row in csv.DictReader(torvik_path.open())]
    canon_set = set(canon)
    aliases: dict[str, str] = {}

    for team in canon:
        for v in _variants(team):
            aliases[_norm_key(v)] = team
        aliases[_norm_key(team)] = team

    for espn, torvik in MANUAL.items():
        if torvik in canon_set:
            aliases[_norm_key(espn)] = torvik

    # ESPN scoreboard locations from Nov 2 2026 slate (opening day).
    fixture = ROOT / "tests" / "fixtures" / "ncaam" / "espn_scoreboard_20261102.json"
    if fixture.exists():
        import json

        payload = json.loads(fixture.read_text())
        for ev in payload.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            for t in comp.get("competitors") or []:
                loc = (t.get("team") or {}).get("location") or ""
                loc = str(loc).strip()
                if not loc:
                    continue
                if _norm_key(loc) in aliases:
                    continue
                hits = [tm for tm in canon if tm.lower().startswith(loc.lower())]
                if len(hits) == 1:
                    aliases[_norm_key(loc)] = hits[0]
                elif loc.endswith(" State"):
                    st = loc[:-6] + " St."
                    if st in canon_set:
                        aliases[_norm_key(loc)] = st
                else:
                    # "Florida State" -> "Florida St." style
                    if loc.endswith(" State"):
                        st = loc[:-6] + " St."
                        hits = [tm for tm in canon if tm.lower() == st.lower()]
                        if len(hits) == 1:
                            aliases[_norm_key(loc)] = hits[0]
                    token = loc.split()[0]
                    hits = [tm for tm in canon if tm.split()[0].lower() == token.lower()]
                    if len(hits) == 1:
                        aliases[_norm_key(loc)] = hits[0]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"canonical": canon, "aliases": aliases}, indent=2) + "\n")
    print(f"Wrote {len(aliases)} alias keys for {len(canon)} Torvik teams -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
