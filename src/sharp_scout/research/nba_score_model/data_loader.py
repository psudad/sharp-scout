"""Load historical NBA games + closing lines from free archives (no Odds API)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from sharp_scout.nba.teams import normalize_nba_team

YAHOO_RAW = "https://raw.githubusercontent.com/csdurfee/scrape_yahoo_odds/main/yahoo_scrapes"
YAHOO_FOLDERS = {"2021-22": "2021", "2022-23": "2022", "2023-24": "2023", "2024-25": "2024"}

YAHOO_TEAM = {
    "Atlanta": "ATL",
    "Boston": "BOS",
    "Brooklyn": "BKN",
    "Charlotte": "CHA",
    "Chicago": "CHI",
    "Cleveland": "CLE",
    "Dallas": "DAL",
    "Denver": "DEN",
    "Detroit": "DET",
    "Golden State": "GSW",
    "Houston": "HOU",
    "Indiana": "IND",
    "LA Clippers": "LAC",
    "LA Lakers": "LAL",
    "Memphis": "MEM",
    "Miami": "MIA",
    "Milwaukee": "MIL",
    "Minnesota": "MIN",
    "New Orleans": "NOP",
    "New York": "NYK",
    "Oklahoma City": "OKC",
    "Orlando": "ORL",
    "Philadelphia": "PHI",
    "Phoenix": "PHX",
    "Portland": "POR",
    "Sacramento": "SAC",
    "San Antonio": "SAS",
    "Toronto": "TOR",
    "Utah": "UTA",
    "Washington": "WAS",
}

SBR_TEAM = {
    "Hawks": "ATL",
    "Celtics": "BOS",
    "Nets": "BKN",
    "Hornets": "CHA",
    "Bulls": "CHI",
    "Cavaliers": "CLE",
    "Mavericks": "DAL",
    "Nuggets": "DEN",
    "Pistons": "DET",
    "Warriors": "GSW",
    "Rockets": "HOU",
    "Pacers": "IND",
    "Clippers": "LAC",
    "Lakers": "LAL",
    "Grizzlies": "MEM",
    "Heat": "MIA",
    "Bucks": "MIL",
    "Timberwolves": "MIN",
    "Pelicans": "NOP",
    "Knicks": "NYK",
    "Thunder": "OKC",
    "Magic": "ORL",
    "76ers": "PHI",
    "Suns": "PHX",
    "Trail Blazers": "POR",
    "Blazers": "POR",
    "Kings": "SAC",
    "Spurs": "SAS",
    "Raptors": "TOR",
    "Jazz": "UTA",
    "Wizards": "WAS",
}


def _parse_yahoo_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_sbr_date(raw: Any) -> datetime | None:
    try:
        s = str(int(float(raw)))
        return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _season_label(dt: datetime) -> str:
    y = dt.year
    if dt.month >= 10:
        return f"{y}-{str(y + 1)[-2:]}"
    return f"{y - 1}-{str(y)[-2:]}"


def _load_csv_url(url: str) -> list[dict[str, str]]:
    with urlopen(url, timeout=120) as resp:  # noqa: S310
        return list(csv.DictReader(io.StringIO(resp.read().decode("utf-8"))))


def load_sbr_games(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out: list[dict[str, Any]] = []
    for g in data:
        season_end = int(g.get("season") or 0)
        if season_end >= 2021:
            continue
        dt = _parse_sbr_date(g.get("date"))
        if dt is None:
            continue
        away = SBR_TEAM.get(str(g.get("away_team") or "").strip(), normalize_nba_team(g["away_team"]))
        home = SBR_TEAM.get(str(g.get("home_team") or "").strip(), normalize_nba_team(g["home_team"]))
        try:
            hs, as_ = int(g["home_final"]), int(g["away_final"])
        except (TypeError, ValueError, KeyError):
            continue
        spread_home = _float(g.get("home_close_spread"))
        total = _float(g.get("close_over_under"))
        if spread_home is None or total is None:
            continue
        out.append(
            {
                "date": dt,
                "season": _season_label(dt),
                "away": away,
                "home": home,
                "away_pts": as_,
                "home_pts": hs,
                "close_spread_home": spread_home,
                "close_total": total,
                "source": "sbr",
            }
        )
    return out


def load_yahoo_games() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for season, folder in YAHOO_FOLDERS.items():
        url = f"{YAHOO_RAW}/{folder}/odds.csv"
        try:
            rows = _load_csv_url(url)
        except Exception:
            continue
        for r in rows:
            dt = _parse_yahoo_date(r.get("game_date", ""))
            if dt is None:
                continue
            away = YAHOO_TEAM.get(r.get("away_team", "").strip(), normalize_nba_team(r["away_team"]))
            home = YAHOO_TEAM.get(r.get("home_team", "").strip(), normalize_nba_team(r["home_team"]))
            spread_home = _float(r.get("spread_home_points"))
            total = _float(r.get("total_over_points"))
            if spread_home is None or total is None:
                continue
            hs = as_ = None
            if r.get("spread_home_won") in ("True", "true", True):
                # infer margin sign from spread result — prefer skip without scores
                pass
            # Yahoo CSV lacks scores; join via ESPN cache later or skip grading without scores
            out.append(
                {
                    "date": dt,
                    "season": season,
                    "away": away,
                    "home": home,
                    "away_pts": None,
                    "home_pts": None,
                    "close_spread_home": spread_home,
                    "close_total": total,
                    "source": "yahoo",
                    "game_id": r.get("game_id"),
                }
            )
    return out


def _float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def enrich_yahoo_with_espn_scores(games: list[dict[str, Any]], score_index: dict[str, dict[str, int]]) -> None:
    for g in games:
        if g.get("home_pts") is not None:
            continue
        key = f"{g['away']}@{g['home']}"
        # also try date-specific keys
        hit = score_index.get(f"{g['date'].date()}|{key}") or score_index.get(key)
        if hit:
            g["home_pts"] = hit["home"]
            g["away_pts"] = hit["away"]


def build_espn_score_index(*, lookback_days: int = 2200, cache_path: Path | None = None) -> dict[str, dict[str, int]]:
    """Date-keyed final scores from ESPN scoreboard (free). Optional JSON cache."""
    if cache_path and cache_path.exists():
        raw = json.loads(cache_path.read_text())
        return {k: {"home": int(v["home"]), "away": int(v["away"])} for k, v in raw.items()}

    from sharp_scout.data import espn_nba as espn

    idx: dict[str, dict[str, int]] = {}
    for row in espn.fetch_espn_nba_scores(lookback_days=lookback_days):
        away, home = row["away_team"], row["home_team"]
        hs, as_ = int(row["home_score"]), int(row["away_score"])
        kick = row.get("kickoff")
        dkey = ""
        if kick:
            try:
                d = datetime.fromisoformat(str(kick).replace("Z", "+00:00")).date()
                dkey = f"{d}|"
            except ValueError:
                dkey = ""
        idx[f"{dkey}{away}@{home}"] = {"home": hs, "away": as_}
        idx[f"{away}@{home}"] = {"home": hs, "away": as_}

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(idx))
    return idx


def load_all_games(
    sbr_path: Path,
    *,
    espn_cache: Path | None = None,
    refresh_espn: bool = False,
) -> list[dict[str, Any]]:
    cache = espn_cache
    if cache and refresh_espn and cache.exists():
        cache.unlink()
    score_index = build_espn_score_index(lookback_days=2200, cache_path=cache)
    games = load_sbr_games(sbr_path)
    yahoo = load_yahoo_games()
    enrich_yahoo_with_espn_scores(yahoo, score_index)
    games.extend([g for g in yahoo if g.get("home_pts") is not None])
    games.sort(key=lambda x: x["date"])
    return games


def load_board_lines_from_shadow(path: Path) -> dict[str, dict[str, float | None]]:
    """Parse latest close spread/total from shadow line history (no API)."""
    if not path.exists():
        return {}
    hist = json.loads(path.read_text())
    out: dict[str, dict[str, float | None]] = {}
    for key, samples in hist.items():
        if not samples or "demo-" in key:
            continue
        parts = key.split("|")
        if len(parts) < 3:
            continue
        eid, market, side = parts[0], parts[1], parts[2]
        last = samples[-1]
        row = out.setdefault(eid, {"spread_home": None, "total": None, "away": None, "home": None})
        if market == "spreads" and side == "home" and last.get("line") is not None:
            row["spread_home"] = float(last["line"])
        if market == "totals" and side == "over" and last.get("line") is not None:
            row["total"] = float(last["line"])
    return out
