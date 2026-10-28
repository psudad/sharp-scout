"""Load historical NBA games + closing lines from free archives (no Odds API)."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from sharp_scout.nba.teams import normalize_nba_team

logger = logging.getLogger(__name__)

YAHOO_RAW = "https://raw.githubusercontent.com/csdurfee/scrape_yahoo_odds/main/yahoo_scrapes"
YAHOO_FOLDERS = {"2021-22": "2021", "2022-23": "2022", "2023-24": "2023", "2024-25": "2024"}

ESPN_SCORE_CACHE_VERSION = 3

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


def _bool_csv(v: Any) -> bool | None:
    if v in (True, "True", "true", "1", 1):
        return True
    if v in (False, "False", "false", "0", 0):
        return False
    return None


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
        open_spread = _float(g.get("home_open_spread"))
        open_total = _float(g.get("open_over_under"))
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
                "open_spread_home": open_spread if open_spread is not None else spread_home,
                "open_total": open_total if open_total is not None else total,
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
            open_spread, open_total = _parse_yahoo_pregame(r.get("pregame_odds", ""))
            if spread_home is None or total is None:
                continue
            out.append(
                {
                    "date": dt,
                    "season": season,
                    "away": away,
                    "home": home,
                    "away_pts": None,
                    "home_pts": None,
                    "open_spread_home": open_spread if open_spread is not None else spread_home,
                    "open_total": open_total if open_total is not None else total,
                    "close_spread_home": spread_home,
                    "close_total": total,
                    "source": "yahoo",
                    "game_id": r.get("game_id"),
                    "spread_home_won": _bool_csv(r.get("spread_home_won")),
                    "total_over_won": _bool_csv(r.get("total_over_won")),
                    "yahoo_spread_stake_pct": _float(r.get("spread_home_stake_percentage")),
                    "yahoo_spread_wager_pct": _float(r.get("spread_home_wager_percentage")),
                }
            )
    return out


def _parse_yahoo_pregame(raw: str) -> tuple[float | None, float | None]:
    if not raw:
        return None, None
    m = re.search(r"([-\d.]+)\s*,\s*O/U\s*([\d.]+)", str(raw), re.I)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def _float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _matchup_key(away: str, home: str) -> str:
    return f"{away}@{home}"


def _home_cover(margin: float, spread_home: float) -> bool | None:
    """True if home covered, None on push."""
    net = margin + spread_home
    if abs(net) < 0.5:
        return None
    return net > 0


def scores_match_yahoo_line(g: dict[str, Any]) -> bool:
    """Use Yahoo's graded spread/total results to verify score↔line join."""
    hs, as_ = g.get("home_pts"), g.get("away_pts")
    if hs is None or as_ is None:
        return False
    margin = float(hs) - float(as_)
    spread = float(g["close_spread_home"])
    total = float(g["close_total"])
    act_total = float(hs) + float(as_)

    shw = g.get("spread_home_won")
    if shw is not None:
        hc = _home_cover(margin, spread)
        if hc is None:
            return False
        if hc != shw:
            return False

    tow = g.get("total_over_won")
    if tow is not None:
        if abs(act_total - total) < 0.5:
            return False
        over = act_total > total
        if over != tow:
            return False

    return True


def _date_candidates(game_date: datetime) -> list[str]:
    d = game_date.date()
    return [(d + timedelta(days=offset)).isoformat() for offset in (0, -1, 1)]


def enrich_yahoo_with_espn_scores(games: list[dict[str, Any]], score_index: dict[str, dict[str, int]]) -> None:
    """Attach ESPN finals only when date+teams match and Yahoo spread/total grades agree."""
    for g in games:
        if g.get("home_pts") is not None:
            continue
        key = _matchup_key(g["away"], g["home"])
        matched = False
        for dstr in _date_candidates(g["date"]):
            hit = score_index.get(f"{dstr}|{key}")
            if not hit:
                continue
            trial = dict(g)
            trial["home_pts"] = hit["home"]
            trial["away_pts"] = hit["away"]
            if scores_match_yahoo_line(trial):
                g["home_pts"] = hit["home"]
                g["away_pts"] = hit["away"]
                g["score_date"] = dstr
                if hit.get("event_id"):
                    g["event_id"] = hit["event_id"]
                matched = True
                break
        if not matched:
            g["home_pts"] = None
            g["away_pts"] = None


def build_espn_score_index(*, lookback_days: int = 2200, cache_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Final scores keyed by ``YYYY-MM-DD|AWY@HOM`` (+ optional ``event_id``)."""
    if cache_path and cache_path.exists():
        payload = json.loads(cache_path.read_text())
        if isinstance(payload, dict) and payload.get("version") == ESPN_SCORE_CACHE_VERSION:
            return {k: dict(v) for k, v in payload["index"].items()}

    from sharp_scout.data import espn_nba as espn

    idx: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for offset in range(lookback_days + 1):
        day = now - timedelta(days=offset)
        dstr = day.strftime("%Y-%m-%d")
        d_api = day.strftime("%Y%m%d")
        try:
            day_rows = espn._fetch_scoreboard({"dates": d_api, "limit": 200})
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESPN scoreboard failed for %s: %s", d_api, exc)
            continue
        for row in day_rows:
            away, home = row["away_team"], row["home_team"]
            hs, as_ = int(row["home_score"]), int(row["away_score"])
            idx[f"{dstr}|{_matchup_key(away, home)}"] = {
                "home": hs,
                "away": as_,
                "event_id": row.get("event_id"),
            }

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"version": ESPN_SCORE_CACHE_VERSION, "index": idx}))
    logger.info("ESPN score index: %d dated keys", len(idx))
    return idx


def _dedupe_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for g in games:
        key = (g["date"].date().isoformat(), g["away"], g["home"])
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


def line_join_diagnostics(games: list[dict[str, Any]]) -> dict[str, Any]:
    """Sanity checks for spread convention (home line) vs actual margins."""
    if not games:
        return {"n": 0}
    nets = []
    within3 = 0
    for g in games:
        margin = float(g["home_pts"]) - float(g["away_pts"])
        net = margin + float(g["close_spread_home"])
        nets.append(net)
        if abs(net) < 3.0:
            within3 += 1
    n = len(nets)
    mean_net = sum(nets) / n
    return {
        "n": n,
        "mean_margin_plus_home_spread": round(mean_net, 4),
        "share_abs_net_under_3": round(within3 / n, 4),
        "std_net": round((sum((x - mean_net) ** 2 for x in nets) / max(n - 1, 1)) ** 0.5, 3),
    }


def sample_join_audit(games: list[dict[str, Any]], *, n: int = 30) -> list[dict[str, Any]]:
    """Hand-check rows: teams, date, line, final, cover result."""
    import random

    pool = [g for g in games if g.get("source") == "yahoo" and g.get("home_pts") is not None]
    if len(pool) <= n:
        sample = pool
    else:
        random.seed(7)
        sample = random.sample(pool, n)
    rows = []
    for g in sorted(sample, key=lambda x: x["date"]):
        margin = int(g["home_pts"]) - int(g["away_pts"])
        spread = float(g["close_spread_home"])
        net = margin + spread
        rows.append(
            {
                "date": g["date"].date().isoformat(),
                "matchup": f"{g['away']} @ {g['home']}",
                "final": f"{g['away_pts']}-{g['home_pts']}",
                "margin": margin,
                "close_spread_home": spread,
                "margin_plus_spread": round(net, 1),
                "close_total": g["close_total"],
                "actual_total": int(g["home_pts"]) + int(g["away_pts"]),
                "yahoo_spread_home_won": g.get("spread_home_won"),
            }
        )
    return rows


def load_all_games(
    sbr_path: Path,
    *,
    espn_cache: Path | None = None,
    refresh_espn: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache = espn_cache
    if cache and refresh_espn and cache.exists():
        cache.unlink()
    score_index = build_espn_score_index(lookback_days=2200, cache_path=cache)
    yahoo_raw = load_yahoo_games()
    enrich_yahoo_with_espn_scores(yahoo_raw, score_index)
    yahoo_joined = [g for g in yahoo_raw if g.get("home_pts") is not None]
    yahoo_rejected = len(yahoo_raw) - len(yahoo_joined)

    games = load_sbr_games(sbr_path)
    games.extend(yahoo_joined)
    games = _dedupe_games(games)
    games.sort(key=lambda x: x["date"])

    meta = {
        "yahoo_rows": len(yahoo_raw),
        "yahoo_joined": len(yahoo_joined),
        "yahoo_rejected_no_match": yahoo_rejected,
        "sbr_rows": len([g for g in games if g.get("source") == "sbr"]),
        "espn_dated_keys": len(score_index),
        "join_audit_sample": sample_join_audit(games),
    }
    meta["line_diagnostics_all"] = line_join_diagnostics(games)
    oos = [g for g in games if g["season"] in ("2022-23", "2023-24", "2024-25")]
    meta["line_diagnostics_oos"] = line_join_diagnostics(oos) if oos else {"n": 0}
    return games, meta


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
