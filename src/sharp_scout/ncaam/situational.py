"""Situational inputs for Sharp 3.5: losing streaks, bounce-back, bubble, star out.

All sources are free (ESPN, Barttorvik); nothing here spends Odds API credits.
Every lookup fails soft: missing data means "signal not present", never an exception.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from sharp_scout.config import DATA_DIR

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
NCAAM_DATA = DATA_DIR / "ncaam"
RESULTS_CACHE = NCAAM_DATA / "results_cache.json"
LOOKBACK_DAYS = 21
SUMMARY = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary"
INJURIES = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/teams/{tid}/injuries"
UA = {"User-Agent": "Mozilla/5.0 (compatible; SharpScout/1.0; +https://github.com/psudad/sharp-scout)"}
BUBBLE_WAB_RANKS = (35, 60)
STAR_USAGE = 25.0


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s or "").lower())


def _torvik_year(day: date) -> int:
    return day.year + 1 if day.month >= 8 else day.year


def selection_sunday(year: int) -> date:
    """Selection Sunday: the Sunday between Mar 11 and Mar 17."""
    d = date(year, 3, 11)
    while d.weekday() != 6:
        d += timedelta(days=1)
    return d


def bubble_season(day: date) -> bool:
    return date(day.year, 2, 1) <= day <= selection_sunday(day.year)


class Situational:
    """Per-pass cache of situational data. ``fetch_json`` is injectable for tests."""

    def __init__(
        self,
        et_day: date,
        *,
        fetch_json: Callable[[str, dict[str, Any] | None], Any] | None = None,
        cache_path: Path | None = None,
        ratings_csv: Path | None = None,
        offline: bool = False,
    ) -> None:
        self.et_day = et_day
        self.offline = offline
        self._fetch = fetch_json or self._http_json
        self.cache_path = cache_path or RESULTS_CACHE
        self.ratings_csv = ratings_csv or (NCAAM_DATA / "ratings_latest.csv")
        self._cache: dict[str, Any] | None = None
        self._dirty = False
        self._usage: dict[str, dict[str, float]] | None = None
        self._injuries: dict[str, list[str]] = {}
        self._wab: dict[str, int] | None = None
        self._mem: dict[str, list[dict[str, Any]]] = {}

    # ---- io -------------------------------------------------------------
    @staticmethod
    def _http_json(url: str, params: dict[str, Any] | None = None) -> Any:
        with httpx.Client(timeout=30.0, headers=UA, follow_redirects=True) as c:
            r = c.get(url, params=params)
            r.raise_for_status()
            return r.json()

    def _load_cache(self) -> dict[str, Any]:
        if self._cache is None:
            try:
                self._cache = json.loads(self.cache_path.read_text())
            except Exception:  # noqa: BLE001
                self._cache = {}
            self._cache.setdefault("days", {})
            self._cache.setdefault("closing", {})
        return self._cache

    def save(self) -> None:
        if not self._dirty or self._cache is None:
            return
        cutoff = (self.et_day - timedelta(days=LOOKBACK_DAYS + 7)).strftime("%Y%m%d")
        self._cache["days"] = {k: v for k, v in self._cache["days"].items() if k >= cutoff}
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, separators=(",", ":"), sort_keys=True) + "\n")
        self._dirty = False

    # ---- results history -----------------------------------------------
    def _day_results(self, d: date) -> list[dict[str, Any]]:
        key = d.strftime("%Y%m%d")
        cache = self._load_cache()
        if key in cache["days"]:
            return cache["days"][key]
        if key in self._mem:
            return self._mem[key]
        if self.offline:
            return []
        from sharp_scout.ncaam.espn import SCOREBOARD, UA as ESPN_UA

        rows: list[dict[str, Any]] = []
        try:
            with httpx.Client(timeout=45.0, headers=ESPN_UA) as c:
                r = c.get(SCOREBOARD, params={"groups": 50, "limit": 400, "dates": key})
                r.raise_for_status()
                payload = r.json()
            for ev in payload.get("events") or []:
                comp = (ev.get("competitions") or [{}])[0]
                st = ((comp.get("status") or {}).get("type") or {})
                if not st.get("completed"):
                    continue
                rec: dict[str, Any] = {"id": str(ev.get("id") or "")}
                for t in comp.get("competitors") or []:
                    side = "h" if t.get("homeAway") == "home" else "a"
                    rec[side] = str((t.get("team") or {}).get("id") or "")
                    rec[side + "s"] = int(t["score"]) if str(t.get("score") or "").isdigit() else None
                if rec.get("hs") is not None and rec.get("as") is not None:
                    rows.append(rec)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESPN results fetch failed for %s: %s", key, type(exc).__name__)
            self._mem[key] = []
            return []
        self._mem[key] = rows
        # Only days at least two days old are final enough to cache (late tips, stat fixes).
        if d <= datetime.now(ET).date() - timedelta(days=2):
            cache["days"][key] = rows
            self._dirty = True
        return rows

    def recent_games(self, team_id: str) -> list[dict[str, Any]]:
        """Completed games before the ET day, newest first: {id, won, home}."""
        out: list[dict[str, Any]] = []
        for i in range(1, LOOKBACK_DAYS + 1):
            d = self.et_day - timedelta(days=i)
            for r in self._day_results(d):
                if team_id not in (r.get("h"), r.get("a")):
                    continue
                home = r.get("h") == team_id
                mine, theirs = (r["hs"], r["as"]) if home else (r["as"], r["hs"])
                out.append({"id": r["id"], "won": mine > theirs, "home": home, "date": d.isoformat()})
        return out

    def losing_streak(self, team_id: str) -> int:
        n = 0
        for g in self.recent_games(team_id):
            if g["won"]:
                break
            n += 1
        return n

    def _closing_line(self, event_id: str, *, home: bool) -> float | None:
        cache = self._load_cache()
        if event_id not in cache["closing"]:
            if self.offline:
                return None
            val = None
            try:
                data = self._fetch(SUMMARY, {"event": event_id})
                pc = (data or {}).get("pickcenter") or []
                if pc and pc[0].get("spread") is not None:
                    val = float(pc[0]["spread"])  # home perspective
            except Exception as exc:  # noqa: BLE001
                logger.info("ESPN pickcenter unavailable for %s: %s", event_id, type(exc).__name__)
                return None
            cache["closing"][event_id] = val
            self._dirty = True
        v = cache["closing"].get(event_id)
        if v is None:
            return None
        return float(v) if home else -float(v)

    def bounce_back(self, team_id: str) -> bool:
        """Previous game was a loss in which the team closed as a 10+ point favorite."""
        games = self.recent_games(team_id)
        if not games or games[0]["won"]:
            return False
        line = self._closing_line(games[0]["id"], home=games[0]["home"])
        return line is not None and line <= -10.0

    # ---- bubble (Torvik WAB rank) ---------------------------------------
    def on_bubble(self, team: str) -> bool:
        if not bubble_season(self.et_day):
            return False
        if self._wab is None:
            self._wab = {}
            try:
                from sharp_scout.ncaam.teams import normalize_ncaam

                with self.ratings_csv.open(newline="") as f:
                    for row in csv.DictReader(f):
                        rk = row.get("WAB Rk")
                        name = normalize_ncaam(row.get("team") or "") or row.get("team")
                        if rk and name:
                            self._wab[name] = int(float(rk))
            except Exception:  # noqa: BLE001
                self._wab = {}
        rk = self._wab.get(team)
        return rk is not None and BUBBLE_WAB_RANKS[0] <= rk <= BUBBLE_WAB_RANKS[1]

    # ---- star protocol ---------------------------------------------------
    def _usage_table(self) -> dict[str, dict[str, float]]:
        if self._usage is not None:
            return self._usage
        path = NCAAM_DATA / f"usage_{self.et_day.strftime('%Y%m%d')}.json"
        if path.exists():
            try:
                self._usage = json.loads(path.read_text())
                return self._usage
            except Exception:  # noqa: BLE001
                pass
        self._usage = {}
        if self.offline:
            return self._usage
        try:
            from sharp_scout.ncaam.teams import normalize_ncaam

            url = f"https://barttorvik.com/getadvstats.php?year={_torvik_year(self.et_day)}&csv=1"
            with httpx.Client(timeout=60.0, headers={"User-Agent": "SharpScout/1.0"}) as c:
                r = c.get(url)
                r.raise_for_status()
            for row in csv.reader(r.text.splitlines()):
                if len(row) < 7:
                    continue
                try:
                    usg = float(row[6])
                except ValueError:
                    continue
                if usg <= STAR_USAGE:
                    continue
                team = normalize_ncaam(row[1]) or row[1]
                self._usage.setdefault(team, {})[_norm_name(row[0])] = usg
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._usage, separators=(",", ":"), sort_keys=True) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.info("Torvik usage unavailable: %s", type(exc).__name__)
        return self._usage

    def players_out(self, team_id: str) -> list[str]:
        if team_id in self._injuries:
            return self._injuries[team_id]
        names: list[str] = []
        if not self.offline and team_id:
            try:
                data = self._fetch(INJURIES.format(tid=team_id), None) or {}
                for item in (data.get("items") or [])[:25]:
                    ref = item.get("$ref") if isinstance(item, dict) else None
                    inj = self._fetch(ref, None) if ref else item
                    status = str((inj or {}).get("status") or (inj.get("type") or {}).get("description") or "")
                    if status.strip().lower() != "out":
                        continue
                    ath = (inj or {}).get("athlete") or {}
                    if "$ref" in ath and "displayName" not in ath:
                        ath = self._fetch(ath["$ref"], None) or {}
                    if ath.get("displayName"):
                        names.append(str(ath["displayName"]))
            except Exception as exc:  # noqa: BLE001
                logger.info("ESPN injuries unavailable for %s: %s", team_id, type(exc).__name__)
        self._injuries[team_id] = names
        return names

    def star_out(self, team: str, team_id: str) -> list[str]:
        """OUT players whose Torvik usage is above 25%."""
        out = self.players_out(team_id)
        if not out:
            return []
        usage = self._usage_table().get(team) or {}
        return [n for n in out if _norm_name(n) in usage]
