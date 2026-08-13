#!/usr/bin/env python3
"""Rebuild docs/ static site for GitHub Pages."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.site.build import build_site  # noqa: E402


def main() -> None:
    out = build_site()
    print(f"Built site → {out}")


if __name__ == "__main__":
    main()
