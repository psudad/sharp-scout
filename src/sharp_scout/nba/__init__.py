"""NBA shadow / paper-trading pipeline (not published to GitHub Pages)."""

from __future__ import annotations

from typing import Any


def run_nba_shadow(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from sharp_scout.nba.pipeline import run_nba_shadow as _run

    return _run(*args, **kwargs)


__all__ = ["run_nba_shadow"]
