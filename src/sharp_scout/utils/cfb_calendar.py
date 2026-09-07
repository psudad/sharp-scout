"""CFB season calendar - automatically determine current week number."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# CFB 2026 season reference dates
SEASON_START_DATES = {
    2026: datetime(2026, 8, 31, tzinfo=ET),  # Week 1 starts Monday Aug 31
    2027: datetime(2027, 8, 30, tzinfo=ET),  # Typically last Monday of August
}


def current_cfb_week(now: datetime | None = None) -> tuple[int, int]:
    """
    Return (season, week) for the current college football week.
    
    Week boundaries: Monday 00:00 ET through Sunday 23:59 ET.
    Week 1 starts the last Monday of August or first Monday of September.
    
    Returns:
        (season_year, week_number) - e.g. (2026, 2)
    """
    now = now or datetime.now(timezone.utc)
    now_et = now.astimezone(ET)
    
    # Determine which season we're in (Aug-Dec = current year, Jan-Jul = prior year)
    if now_et.month >= 8:
        season = now_et.year
    else:
        season = now_et.year - 1
    
    # Get the season start date
    if season not in SEASON_START_DATES:
        # Fallback: assume last Monday of August
        aug_31 = datetime(season, 8, 31, tzinfo=ET)
        # Go back to the nearest Monday
        days_since_monday = aug_31.weekday()
        season_start = aug_31.replace(hour=0, minute=0, second=0, microsecond=0)
        if days_since_monday > 0:
            from datetime import timedelta
            season_start = season_start - timedelta(days=days_since_monday)
    else:
        season_start = SEASON_START_DATES[season]
    
    # Calculate weeks elapsed since season start
    days_since_start = (now_et - season_start).days
    if days_since_start < 0:
        # Before season starts, return Week 0 (preseason)
        return (season, 0)
    
    week = (days_since_start // 7) + 1  # Week 1, Week 2, etc.
    
    return (season, week)
