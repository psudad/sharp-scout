"""Walk-forward backtest of NBA shadow game-line model on free historical odds.

Data: BetMGM closing lines via Yahoo (csdurfee/scrape_yahoo_odds, CC-BY research use).
Single-book limitation: we synthesize Pinnacle/DraftKings from close and FanDuel as close
with a small retail price penalty so the production EV scanner can run unchanged.
Props: no free historical player-prop lines at scale — skipped (documented in report).

All grades use closing lines (pregame close as scraped by Yahoo).
"""

from __future__ import annotations

import csv
import io
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from sharp_scout.ledger.tracker import american_profit, settle_play
from sharp_scout.nba.game_lines import (
    LONG_DOG_PRICE_FLOOR,
    discover_game_line_edges,
    scan_game_line_opportunities,
)
from sharp_scout.nba.teams import normalize_nba_team
from sharp_scout.utils.odds import american_to_implied_prob

logger = logging.getLogger(__name__)

YAHOO_RAW_BASE = (
    "https://raw.githubusercontent.com/csdurfee/scrape_yahoo_odds/main/yahoo_scrapes"
)
# Folder year on Yahoo repo → NBA season label (season ending year).
YAHOO_SEASON_FILES: dict[str, str] = {
    "2021-22": "2021",
    "2022-23": "2022",
    "2023-24": "2023",
    "2024-25": "2024",
}

YAHOO_TEAM: dict[str, str] = {
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

SHARP_PRICE_BONUS = 10.0  # Pinnacle price improvement vs retail (single-book proxy)
RETAIL_SPREAD_TOTAL_HALF_PT = 1.0  # FanDuel line penalty vs sharp at close


def _yahoo_team(name: str) -> str:
    return YAHOO_TEAM.get(str(name).strip(), normalize_nba_team(name))


def _worse_american(price: float, penalty: float = SHARP_PRICE_BONUS) -> float:
    p = float(price)
    return p - penalty if p >= 0 else p - penalty


def _better_american(price: float, bonus: float = SHARP_PRICE_BONUS) -> float:
    p = float(price)
    return p + bonus if p >= 0 else p + bonus


def _load_csv_url(url: str) -> list[dict[str, str]]:
    with urlopen(url, timeout=120) as resp:  # noqa: S310
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


SBR_TEAM: dict[str, str] = {
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


def _sbr_team(name: str) -> str:
    return SBR_TEAM.get(str(name).strip(), normalize_nba_team(name))


def load_sbr_archive(path: Path) -> list[dict[str, Any]]:
    import json

    if not path.exists():
        return []
    data = json.loads(path.read_text())
    rows: list[dict[str, Any]] = []
    for g in data:
        season = int(g.get("season") or 0)
        if season >= 2021:
            continue  # Yahoo MGM archive covers 2021-22 onward (avoid double-count)
        label = f"{season - 1}-{str(season)[-2:]}"
        rows.append(
            {
                "_season": label,
                "_source": "sbr",
                "game_date": str(int(g.get("date") or 0)),
                "away_team": _sbr_team(g.get("away_team", "")),
                "home_team": _sbr_team(g.get("home_team", "")),
                "home_final": g.get("home_final"),
                "away_final": g.get("away_final"),
                "pin_spread_home": _float(g.get("home_close_spread")),
                "pin_spread_away": _float(g.get("away_close_spread")),
                "fd_spread_home": _float(g.get("home_open_spread")),
                "fd_spread_away": _float(g.get("away_open_spread")),
                "pin_total": _float(g.get("close_over_under")),
                "fd_total": _float(g.get("open_over_under")),
                "pin_ml_home": _float(g.get("home_close_ml")),
                "pin_ml_away": _float(g.get("away_close_ml")),
                "fd_ml_home": _float(g.get("home_close_ml")),  # SBR lacks open ML; price penalty only
                "fd_ml_away": _float(g.get("away_close_ml")),
            }
        )
    return rows


def _mk_outcome(side: str, price: Any, point: Any) -> dict[str, Any] | None:
    if price is None and point is None:
        return None
    p = _float(price) if price is not None else -110.0
    if p == 0:
        return None
    o: dict[str, Any] = {"side": side, "price": p}
    if point is not None:
        o["point"] = float(point)
    return o


def sbr_row_to_event(row: dict[str, Any]) -> dict[str, Any] | None:
    """Map SBR close lines into the same synthetic retail model as Yahoo (not open-vs-close)."""
    yahoo_like = {
        "away_team": row.get("away_team"),
        "home_team": row.get("home_team"),
        "spread_away_points": row.get("pin_spread_away"),
        "spread_home_points": row.get("pin_spread_home"),
        "spread_away_odds": -110,
        "spread_home_odds": -110,
        "total_over_points": row.get("pin_total"),
        "total_under_points": row.get("pin_total"),
        "total_over_odds": -110,
        "total_under_odds": -110,
        "money_away_odds": row.get("pin_ml_away"),
        "money_home_odds": row.get("pin_ml_home"),
    }
    ev = yahoo_row_to_event(yahoo_like)
    return ev


def load_yahoo_seasons(
    seasons: list[str] | None = None,
    *,
    extra_csv_paths: list[Path] | None = None,
) -> list[dict[str, Any]]:
    seasons = seasons or list(YAHOO_SEASON_FILES.keys())
    rows: list[dict[str, Any]] = []
    for label in seasons:
        folder = YAHOO_SEASON_FILES.get(label)
        if not folder:
            continue
        url = f"{YAHOO_RAW_BASE}/{folder}/odds.csv"
        try:
            chunk = _load_csv_url(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load %s: %s", url, exc)
            continue
        for r in chunk:
            r["_season"] = label
            rows.append(r)
    for path in extra_csv_paths or []:
        if path.exists():
            for r in csv.DictReader(path.open()):
                r.setdefault("_season", "2025-26")
                rows.append(r)
    return rows


def _float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bool(v: Any) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes")


def yahoo_row_to_event(row: dict[str, Any]) -> dict[str, Any] | None:
    away = _yahoo_team(row.get("away_team", ""))
    home = _yahoo_team(row.get("home_team", ""))
    if not away or not home:
        return None

    def mk_outcome(side: str, price: float | None, point: float | None) -> dict[str, Any] | None:
        if price is None or float(price) == 0:
            return None
        o: dict[str, Any] = {"side": side, "price": float(price)}
        if point is not None:
            o["point"] = float(point)
        return o

    pin_spread = [
        mk_outcome("away", _float(row.get("spread_away_odds")) or -110, _float(row.get("spread_away_points"))),
        mk_outcome("home", _float(row.get("spread_home_odds")) or -110, _float(row.get("spread_home_points"))),
    ]
    pin_total = [
        mk_outcome("over", _float(row.get("total_over_odds")) or -110, _float(row.get("total_over_points"))),
        mk_outcome("under", _float(row.get("total_under_odds")) or -110, _float(row.get("total_under_points"))),
    ]
    pin_h2h = [
        mk_outcome("away", _better_american(_float(row.get("money_away_odds")) or 100), None),
        mk_outcome("home", _better_american(_float(row.get("money_home_odds")) or -100), None),
    ]
    fd_spread_raw = [
        mk_outcome("away", _float(row.get("spread_away_odds")), _float(row.get("spread_away_points"))),
        mk_outcome("home", _float(row.get("spread_home_odds")), _float(row.get("spread_home_points"))),
    ]
    fd_total_raw = [
        mk_outcome("over", _float(row.get("total_over_odds")), _float(row.get("total_over_points"))),
        mk_outcome("under", _float(row.get("total_under_odds")), _float(row.get("total_under_points"))),
    ]
    fd_h2h_raw = [
        mk_outcome("away", _float(row.get("money_away_odds")), None),
        mk_outcome("home", _float(row.get("money_home_odds")), None),
    ]
    pin_spread = [x for x in pin_spread if x]
    pin_total = [x for x in pin_total if x]
    pin_h2h = [x for x in pin_h2h if x]
    if len(pin_spread) < 2 or len(pin_total) < 2 or len(pin_h2h) < 2:
        return None

    fd_spread_raw = [x for x in fd_spread_raw if x]
    fd_total_raw = [x for x in fd_total_raw if x]
    fd_h2h_raw = [x for x in fd_h2h_raw if x]

    fd_spread = []
    for o in fd_spread_raw:
        pt = o.get("point")
        new_pt = float(pt) if pt is not None else None
        if new_pt is not None:
            new_pt = new_pt + RETAIL_SPREAD_TOTAL_HALF_PT if o["side"] == "home" else new_pt - RETAIL_SPREAD_TOTAL_HALF_PT
        fd_spread.append({**o, "point": new_pt})
    fd_total = []
    for o in fd_total_raw:
        pt = o.get("point")
        new_pt = float(pt) if pt is not None else None
        if new_pt is not None:
            new_pt = new_pt + RETAIL_SPREAD_TOTAL_HALF_PT if o["side"] == "over" else new_pt - RETAIL_SPREAD_TOTAL_HALF_PT
        fd_total.append({**o, "point": new_pt})
    fd_h2h = list(fd_h2h_raw)

    return {
        "event_id": str(row.get("game_id") or ""),
        "away_team": away,
        "home_team": home,
        "commence_time": row.get("game_date"),
        "bookmakers": {
            "pinnacle": {
                "is_sharp": True,
                "markets": {"spreads": pin_spread, "totals": pin_total, "h2h": pin_h2h},
            },
            "draftkings": {
                "markets": {"spreads": list(pin_spread), "totals": list(pin_total), "h2h": list(pin_h2h)},
            },
            "fanduel": {
                "markets": {"spreads": fd_spread, "totals": fd_total, "h2h": fd_h2h},
            },
        },
    }


def _scores_from_yahoo(row: dict[str, Any], score_index: dict[str, dict[str, Any]]) -> tuple[int, int] | None:
    away = _yahoo_team(row.get("away_team", ""))
    home = _yahoo_team(row.get("home_team", ""))
    hit = score_index.get(f"{away}@{home}")
    if not hit:
        return None
    try:
        return int(hit["home_score"]), int(hit["away_score"])
    except (TypeError, ValueError, KeyError):
        return None


def _grade_from_yahoo_flags(row: dict[str, Any], market: str, side: str) -> str | None:
    if market == "h2h":
        if side == "away":
            w = _bool(row.get("money_away_won"))
        else:
            w = _bool(row.get("money_home_won"))
    elif market == "spreads":
        if side == "away":
            w = _bool(row.get("spread_away_won"))
        else:
            w = _bool(row.get("spread_home_won"))
    elif market == "totals":
        if side == "over":
            w = _bool(row.get("total_over_won"))
        else:
            w = _bool(row.get("total_under_won"))
    else:
        return None
    if w is None:
        return None
    return "win" if w else "loss"


def _ml_bucket(price: float) -> str:
    if price < 0:
        return "favorite"
    if price < LONG_DOG_PRICE_FLOOR:
        return "short_dog"
    return "long_dog"


@dataclass
class BetRow:
    season: str
    game_date: str
    away: str
    home: str
    market: str
    side: str
    line: float | None
    price: float
    p_true: float
    edge: float
    gate: str  # all_positive | pick | possible
    status: str
    pnl_1u: float
    pnl_close: float
    actual_margin: float | None = None
    close_line_margin: float | None = None


@dataclass
class BacktestResult:
    bets: list[BetRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def run_game_line_backtest(
    rows: list[dict[str, Any]],
    *,
    score_index: dict[str, dict[str, Any]] | None = None,
) -> BacktestResult:
    score_index = score_index or {}
    out = BacktestResult()
    out.notes.append(
        "Closing lines only (SBR 2010-11–2020-21 close; Yahoo BetMGM 2021-22–2024-25 close). "
        "Synthetic sharp=close; FanDuel=close with "
        f"Pinnacle +{SHARP_PRICE_BONUS:.0f}c vs retail at same close; FanDuel +{RETAIL_SPREAD_TOTAL_HALF_PT:.1f}pt line penalty. "
        "2025-26 not in Yahoo GitHub CSVs (run script with --fetch-2025-26 to scrape). "
        "Props skipped — no free historical player-prop archive."
    )

    for row in rows:
        source = str(row.get("_source") or "yahoo")
        if source == "sbr":
            ev = sbr_row_to_event(row)
        else:
            ev = yahoo_row_to_event(row)
        if not ev:
            continue
        season = str(row.get("_season") or "")
        gdate = str(row.get("game_date") or "")[:10]
        away, home = ev["away_team"], ev["home_team"]
        hs = as_ = None
        if source == "sbr":
            try:
                hs, as_ = int(row["home_final"]), int(row["away_final"])
            except (TypeError, ValueError, KeyError):
                hs = as_ = None
        else:
            scores = _scores_from_yahoo(row, score_index)
            if scores:
                hs, as_ = scores
        margin = (hs - as_) if hs is not None and as_ is not None else None

        try:
            opps = scan_game_line_opportunities(ev)
            picks = discover_game_line_edges(ev)
        except Exception as exc:  # noqa: BLE001
            logger.debug("scan skipped %s@%s: %s", away, home, exc)
            continue
        pick_keys = {(p.market, p.side) for p in picks}

        def emit(opp: dict[str, Any], gate: str) -> None:
            market = str(opp["market"])
            side = str(opp["side"])
            price = float(opp["price"])
            line = opp.get("line")
            if price == 0 or abs(price) > 5000:
                return

            status = None if source == "sbr" else _grade_from_yahoo_flags(row, market, side)
            if status is None and hs is not None and as_ is not None:
                play = {
                    "market": market,
                    "side": side,
                    "line": line,
                    "price": price,
                    "units": 1.0,
                    "play_type": "side",
                }
                graded = settle_play(dict(play), hs, as_)
                status = str(graded.get("status") or "")
            if status not in ("win", "loss", "push"):
                return

            pnl_1u = american_profit(1.0, price) if status == "win" else (-1.0 if status == "loss" else 0.0)

            close_line_margin = None
            if margin is not None and market == "spreads" and line is not None:
                if side == "home":
                    close_line_margin = float(line)
                else:
                    close_line_margin = -float(line)

            out.bets.append(
                BetRow(
                    season=season,
                    game_date=gdate,
                    away=away,
                    home=home,
                    market=market,
                    side=side,
                    line=float(line) if line is not None else None,
                    price=price,
                    p_true=float(opp.get("p_true") or 0),
                    edge=float(opp.get("edge") or 0),
                    gate=gate,
                    status=status,
                    pnl_1u=round(pnl_1u, 4),
                    pnl_close=round(pnl_1u, 4),
                    actual_margin=float(margin) if margin is not None else None,
                    close_line_margin=close_line_margin,
                )
            )

        for opp in opps:
            if float(opp.get("edge") or 0) <= 0:
                continue
            key = (str(opp["market"]), str(opp["side"]))
            if key in pick_keys:
                emit(opp, "pick")
            elif not opp.get("qualified"):
                emit(opp, "possible")

        # One side per market: highest-edge scan row (every-game model lean).
        by_market: dict[str, dict[str, Any]] = {}
        for opp in opps:
            m = str(opp["market"])
            if float(opp.get("edge") or 0) <= 0:
                continue
            prev = by_market.get(m)
            if prev is None or float(opp["edge"]) > float(prev["edge"]):
                by_market[m] = opp
        for opp in by_market.values():
            emit(opp, "every_game")

    return out


def _record_units(bets: list[BetRow], *, gate: str | None = None, market: str | None = None) -> dict[str, Any]:
    subset = bets
    if gate:
        subset = [b for b in subset if b.gate == gate]
    if market:
        subset = [b for b in subset if b.market == market]
    wins = sum(1 for b in subset if b.status == "win")
    losses = sum(1 for b in subset if b.status == "loss")
    pushes = sum(1 for b in subset if b.status == "push")
    units = sum(b.pnl_1u for b in subset)
    return {
        "n": len(subset),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "units": round(units, 2),
    }


def _calibration(bets: list[BetRow], *, gate: str = "pick") -> list[dict[str, Any]]:
    picks = [b for b in bets if b.gate == gate and b.status in ("win", "loss")]
    if not picks:
        return []
    picks.sort(key=lambda b: b.p_true)
    n_bins = 5
    chunk = max(1, len(picks) // n_bins)
    bins: list[dict[str, Any]] = []
    for i in range(0, len(picks), chunk):
        part = picks[i : i + chunk]
        if not part:
            continue
        avg_p = sum(b.p_true for b in part) / len(part)
        wr = sum(1 for b in part if b.status == "win") / len(part)
        bins.append({"n": len(part), "avg_p_true": round(avg_p, 4), "win_rate": round(wr, 4)})
    return bins


def _edge_buckets(bets: list[BetRow], *, gate: str = "pick") -> list[dict[str, Any]]:
    picks = [b for b in bets if b.gate == gate and b.status in ("win", "loss")]
    edges = [(b.edge, b.status) for b in picks]
    cuts = [0.02, 0.04, 0.06, 0.08, 0.12, 1.0]
    out = []
    for lo, hi in zip(cuts, cuts[1:]):
        bucket = [s for e, s in edges if lo <= e < hi]
        if not bucket:
            continue
        wr = sum(1 for s in bucket if s == "win") / len(bucket)
        out.append({"edge_lo": lo, "edge_hi": hi, "n": len(bucket), "win_rate": round(wr, 4)})
    return out


def _margin_mae(bets: list[BetRow], *, gate: str = "pick") -> dict[str, float | None]:
    """Spread-only: MAE of closing line vs actual margin (market baseline)."""
    rows = [
        b
        for b in bets
        if b.gate == gate and b.market == "spreads" and b.actual_margin is not None and b.close_line_margin is not None
    ]
    if not rows:
        return {"market_spread_mae": None, "n": 0}
    errs = [abs(b.actual_margin - b.close_line_margin) for b in rows]
    return {"market_spread_mae": round(sum(errs) / len(errs), 3), "n": len(rows)}


def build_score_index(*, lookback_days: int = 400) -> dict[str, dict[str, Any]]:
    from sharp_scout.data import espn_nba as espn_nba_mod

    idx: dict[str, dict[str, Any]] = {}
    for g in espn_nba_mod.fetch_espn_nba_scores(lookback_days=lookback_days):
        idx[f"{g['away_team']}@{g['home_team']}"] = g
    return idx


def summarize_backtest(result: BacktestResult) -> dict[str, Any]:
    bets = result.bets
    summary: dict[str, Any] = {
        "notes": result.notes,
        "n_opportunities": len(bets),
        "every_game": _record_units(bets, gate="every_game"),
        "picks": _record_units(bets, gate="pick"),
        "possible": _record_units(bets, gate="possible"),
        "by_market": {},
        "h2h_by_bucket": {},
        "calibration_picks": _calibration(bets, gate="pick"),
        "edge_buckets_picks": _edge_buckets(bets, gate="pick"),
        "spread_mae_picks": _margin_mae(bets, gate="pick"),
    }
    for mkt in ("spreads", "totals", "h2h"):
        summary["by_market"][mkt] = {
            "all": _record_units(bets, market=mkt),
            "picks": _record_units(bets, gate="pick", market=mkt),
            "possible": _record_units(bets, gate="possible", market=mkt),
        }
    h2h = [b for b in bets if b.market == "h2h" and b.gate == "pick"]
    for label in ("favorite", "short_dog", "long_dog"):
        bucket = [b for b in h2h if _ml_bucket(b.price) == label]
        summary["h2h_by_bucket"][label] = _record_units(bucket)
    by_season: dict[str, Any] = defaultdict(list)
    for b in bets:
        by_season[b.season].append(b)
    summary["by_season_picks"] = {
        s: _record_units(v, gate="pick") for s, v in sorted(by_season.items())
    }
    return summary


def write_csv(path: Path, bets: list[BetRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "season",
        "game_date",
        "away",
        "home",
        "market",
        "side",
        "line",
        "price",
        "p_true",
        "edge",
        "gate",
        "status",
        "pnl_1u",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for b in bets:
            w.writerow({k: getattr(b, k) for k in fields})


def render_markdown(summary: dict[str, Any], *, title: str) -> str:
    lines = [
        f"# {title}",
        "",
        "Research only — **not** wired into live NBA or football pipelines.",
        "",
        "## Data & methodology",
        "",
    ]
    for note in summary.get("notes") or []:
        lines.append(f"- {note}")
    lines.extend(
        [
            "- Walk-forward: each game uses only its pregame closing snapshot (no future stats).",
            "- **Props:** skipped — no free multi-season historical player-prop closing lines found.",
            "",
            "## Every game (best +EV side per market at close)",
            "",
            f"- **Record:** {summary['every_game']['record']} on {summary['every_game']['n']} bets",
            f"- **Units @ 1u flat (actual close price):** {summary['every_game']['units']}",
            "",
            "## Headline — Picks gate (production `discover_game_line_edges` + long-dog rule)",
            "",
            f"- **Record:** {summary['picks']['record']} on {summary['picks']['n']} bets",
            f"- **Units @ 1u flat:** {summary['picks']['units']}",
            "",
            "## Possible picks (positive EV, failed qualification)",
            "",
            f"- **Record:** {summary['possible']['record']} ({summary['possible']['units']}u)",
            "",
            "## By market (Picks)",
            "",
            "| Market | N | Record | Units |",
            "|--------|---|--------|-------|",
        ]
    )
    for mkt, block in (summary.get("by_market") or {}).items():
        p = block["picks"]
        if p["n"]:
            lines.append(f"| {mkt} | {p['n']} | {p['record']} | {p['units']} |")
    lines.extend(["", "## Moneyline Picks by price bucket", ""])
    for label, rec in (summary.get("h2h_by_bucket") or {}).items():
        if rec["n"]:
            lines.append(f"- **{label}:** {rec['record']} ({rec['units']}u, n={rec['n']})")
    lines.extend(["", "## Calibration (Picks, p_true bins)", ""])
    for row in summary.get("calibration_picks") or []:
        lines.append(
            f"- n={row['n']} avg_p={row['avg_p_true']:.3f} actual_win={row['win_rate']:.3f}"
        )
    lines.extend(["", "## Win rate by edge bucket (Picks)", ""])
    for row in summary.get("edge_buckets_picks") or []:
        lines.append(
            f"- EV {row['edge_lo']:.0%}–{row['edge_hi']:.0%}: n={row['n']} win={row['win_rate']:.3f}"
        )
    mae = summary.get("spread_mae_picks") or {}
    lines.extend(
        [
            "",
            "## Spread line error (market baseline)",
            "",
            f"- MAE of home margin vs closing spread line (Picks subset): **{mae.get('market_spread_mae')}** (n={mae.get('n')})",
            "- The shadow game-line model has **no independent margin/total simulator**; edge is purely retail-vs-sharp price. "
            "Spread 'model error' equals market close error by construction.",
            "",
            "## Plain-English verdict",
            "",
            _verdict(summary),
            "",
            "## Suggested fixes (proposals only)",
            "",
            "1. **Require multi-book historical snapshots** (or paid Odds API history) before trusting CLV/EV backtests — single-book synthesis inflates apparent edge.",
            "2. **Keep long-dog shrink**; backtest ML long-dog bucket separately — if still negative after gate, raise slope or cap ML dogs entirely.",
            "3. **Add a real team-strength or pace layer** for totals/spreads so margin/total error can be measured against the market, not just price mirroring.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _verdict(summary: dict[str, Any]) -> str:
    picks = summary.get("picks") or {}
    units = float(picks.get("units") or 0)
    n = int(picks.get("n") or 0)
    if n < 100:
        base = f"Sample of {n} Picks is too small for a firm conclusion, but "
    else:
        base = f"Over {n} Picks, "
    if units < -5:
        tail = (
            "the closing-line retail-vs-sharp heuristic **does not show positive flat units**. "
            "Moneyline long-dog and possible-pick buckets are the likeliest leak areas."
        )
    elif units > 5:
        tail = "flat units are positive, but **single-book synthesis may overstate edge** — treat as directional only until multi-book history exists."
    else:
        tail = "results are **near breakeven**, consistent with a vig-adjusted market; no strong evidence of durable edge without better odds archives."
    h2h = summary.get("h2h_by_bucket") or {}
    long_d = h2h.get("long_dog") or {}
    if long_d.get("n") and float(long_d.get("units") or 0) < 0:
        tail += " Long ML (+300+) Picks remain negative in this archive."
    return base + tail
