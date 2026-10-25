"""NBA shadow / paper-trading pipeline (not published to GitHub Pages)."""

__all__ = ["run_nba_shadow"]


def __getattr__(name: str):
    if name == "run_nba_shadow":
        from sharp_scout.nba.pipeline import run_nba_shadow

        return run_nba_shadow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
