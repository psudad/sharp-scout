# Research data cache (local only)

- **`nba_archive_10Y.json`**: SBR-style NBA archive (scores + closing spread/total). Clone [sbr-scraper](https://github.com/robk5/sbr-scraper) and copy `data/nba_archive_10Y.json`, or reuse a cached copy from a prior research run.
- **`espn_nba_score_index.json`**: Built by `python scripts/run_nba_score_model.py --refresh-espn` (ESPN scoreboard day-by-day, versioned `YYYY-MM-DD|AWY@HOM` keys; gitignored). Yahoo rows are joined only when dated keys match and Yahoo spread/total grades agree.

Neither file is required for unit tests.
