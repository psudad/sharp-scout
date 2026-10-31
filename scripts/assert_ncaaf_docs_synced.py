#!/usr/bin/env python3
"""Fail CI when docs/ NCAAF signals are older than the pipeline artifact."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import ARTIFACTS_DIR  # noqa: E402
from sharp_scout.site.build import DOCS_DIR  # noqa: E402
from sharp_scout.sports import NCAAF  # noqa: E402
from sharp_scout.utils.slate import parse_commence  # noqa: E402


def main() -> None:
    art_path = ARTIFACTS_DIR / NCAAF.artifact_name
    doc_path = DOCS_DIR / "latest_ncaaf_signals.json"
    if not art_path.exists():
        print(f"No artifact at {art_path} — skip sync check")
        return
    if not doc_path.exists():
        raise SystemExit(f"Missing {doc_path} after NCAAF run (artifact exists)")

    art = json.loads(art_path.read_text())
    doc = json.loads(doc_path.read_text())
    art_ts = parse_commence(art.get("generated_at"))
    doc_ts = parse_commence(doc.get("generated_at"))
    if art_ts is None or doc_ts is None:
        raise SystemExit("NCAAF signals missing generated_at in artifact or docs")

    if doc_ts < art_ts:
        raise SystemExit(
            f"docs/latest_ncaaf_signals.json is stale: docs={doc_ts.isoformat()} "
            f"artifact={art_ts.isoformat()} (week doc={doc.get('week')} art={art.get('week')})"
        )
    if doc.get("week") != art.get("week") and doc_ts <= art_ts:
        raise SystemExit(
            f"docs week {doc.get('week')} != artifact week {art.get('week')} "
            f"(generated_at docs={doc_ts.isoformat()} art={art_ts.isoformat()})"
        )
    print(f"NCAAF docs in sync with artifact (week={art.get('week')}, {doc_ts.isoformat()})")


if __name__ == "__main__":
    main()
