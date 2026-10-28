"""Research-only CLV / early-line backtests for NFL totals (not used in production)."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from sharp_scout.data.line_store import closing_sample, load_history, opening_sample, samples_for
from sharp_scout.data.nflfastr import load_schedules
from sharp_scout.ledger.clv import clv_points, clv_prob
from sharp_scout.nfl.totals.walk_forward import (
    append_completed_from_schedules,
    load_games_from_csv,
    run_walk_forward_backtest,
)
from sharp_scout.utils.odds import american_to_implied_prob, normalize_team

KEY_TOTALS = (37.0, 41.0, 43.0, 44.0, 47.0, 51.0)
MIN_MEANINGFUL = 20


def _parse_ts(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _parse_kickoff(row: pd.Series) -> datetime | None:
    gday = row.get("gameday")
    if gday is None or (isinstance(gday, float) and math.isnan(gday)):
        return None
    gt = row.get("gametime") or "13:00"
    try:
        local = datetime.strptime(f"{str(gday)[:10]} {gt}", "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            local = datetime.strptime(str(gday)[:10], "%Y-%m-%d")
        except ValueError:
            return None
    # nflverse gametime is Eastern; store as UTC-ish offset for ordering (ET ≈ UTC-4/5)
    return local.replace(tzinfo=timezone.utc)


def _grade(side: str, line: float, final_total: float) -> str:
    if final_total > line:
        winner = "over"
    elif final_total < line:
        winner = "under"
    else:
        return "P"
    return "W" if side == winner else "L"


def _units(result: str, american: int | None) -> float:
    if result == "P":
        return 0.0
    if result == "L":
        return -1.0
    if american is None:
        return 100.0 / 110.0
    if american >= 0:
        return american / 100.0
    return 100.0 / abs(american)


def _no_vig_prob(over_price: int, under_price: int) -> tuple[float, float]:
    p_o = american_to_implied_prob(float(over_price))
    p_u = american_to_implied_prob(float(under_price))
    s = p_o + p_u
    if s <= 0:
        return 0.5, 0.5
    return p_o / s, p_u / s


@dataclass
class GameContext:
    season: int
    week: int
    away: str
    home: str
    event_id: str
    kickoff: datetime | None
    final_total: float
    spread_line: float | None
    wind: float | None
    roof: str | None


@dataclass
class ScanRow:
    """One early snapshot → hypothetical bet vs later Pinnacle close."""
    game: GameContext
    scan_ts: str
    hours_before_kick: float | None
    scan_line: float
    scan_over_price: int
    scan_under_price: int | None
    close_line: float
    close_over_price: int
    close_under_price: int | None
    side: str
    signal: str
    betfair_line: float | None
    open_line: float | None
    sim_median_cal: float | None
    wind: float | None
    roof: str | None
    meta: dict[str, Any] = field(default_factory=dict)


def build_nfl_event_catalog() -> dict[str, dict[str, Any]]:
    """Odds API event_id → teams/kickoff from ledger + totals tracker + latest signals."""
    catalog: dict[str, dict[str, Any]] = {}
    paths = [
        Path("data/ledger.json"),
        Path("docs/ledger.json"),
        Path("data/nfl_game_totals.json"),
    ]
    for path in paths:
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        rows = data.get("plays") if "plays" in data else data.get("games", [])
        for row in rows:
            eid = row.get("event_id")
            if not eid:
                continue
            sport = row.get("sport")
            if sport and sport != "nfl":
                continue
            catalog[str(eid)] = {
                "away": normalize_team(row.get("away_team") or row.get("away") or "", "nfl"),
                "home": normalize_team(row.get("home_team") or row.get("home") or "", "nfl"),
                "kickoff": row.get("kickoff") or row.get("commence_time"),
            }
    sig_path = Path("docs/latest_signals.json")
    if sig_path.exists():
        for g in json.loads(sig_path.read_text()).get("games", []):
            eid = g.get("event_id")
            if eid:
                catalog[str(eid)] = {
                    "away": normalize_team(g.get("away") or g.get("away_team") or "", "nfl"),
                    "home": normalize_team(g.get("home") or g.get("home_team") or "", "nfl"),
                    "kickoff": g.get("commence_time") or g.get("kickoff"),
                }
    return catalog


def match_event_ids_to_schedule(
    sched: pd.DataFrame,
    catalog: dict[str, dict[str, Any]],
    history: dict[str, list[dict[str, Any]]],
) -> dict[tuple[int, str, str], str]:
    """Map (week, away, home) → event_id via catalog, then spread-line fingerprint."""
    out: dict[tuple[int, str, str], str] = {}
    for _, row in sched.iterrows():
        away = normalize_team(str(row["away_team"]), "nfl")
        home = normalize_team(str(row["home_team"]), "nfl")
        week = int(row["week"])
        key = (week, away or "", home or "")
        for eid, meta in catalog.items():
            if meta.get("away") == away and meta.get("home") == home:
                out[key] = eid
                break

    # Fingerprint match for games still missing
    missing = []
    for _, row in sched.iterrows():
        away = normalize_team(str(row["away_team"]), "nfl")
        home = normalize_team(str(row["home_team"]), "nfl")
        week = int(row["week"])
        key = (week, away or "", home or "")
        if key in out:
            continue
        try:
            tgt_spread = float(row["spread_line"])
            tgt_total = float(row["total_line"])
        except (TypeError, ValueError):
            missing.append(key)
            continue
        best_eid = None
        best_score = 999.0
        for eid in {k.split("|")[0] for k in history if "|totals|" in k}:
            close_t = closing_sample(eid, "totals", "over", history=history)
            close_s = closing_sample(eid, "spreads", "home", history=history)
            if not close_t or not close_s:
                continue
            try:
                score = abs(float(close_t["line"]) - tgt_total) + abs(
                    float(close_s["line"]) - tgt_spread
                )
            except (TypeError, ValueError):
                continue
            if score < best_score:
                best_score = score
                best_eid = eid
        if best_eid and best_score <= 1.5:
            out[key] = best_eid
    return out


def _price_at(samples: list[dict[str, Any]], ts: datetime, book: str) -> dict[str, Any] | None:
    eligible = [
        s
        for s in samples
        if s.get("book") == book and (_parse_ts(s.get("ts")) or ts) <= ts
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda s: str(s.get("ts") or ""))


def _under_sample_at(
    history: dict[str, list],
    eid: str,
    ts: datetime,
    book: str = "pinnacle",
) -> dict[str, Any] | None:
    samples = samples_for(eid, "totals", "under", history=history)
    return _price_at(samples, ts, book)


def load_sim_by_match(csv_path: Path | None) -> dict[tuple[int, str, str], float]:
    """Calibrated sim median keyed by (week, away, home) from season backtest CSV."""
    out: dict[tuple[int, str, str], float] = {}
    if csv_path is None or not csv_path.exists():
        return out
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                wk = int(row["week"])
                away = normalize_team(row["away"], "nfl") or row["away"]
                home = normalize_team(row["home"], "nfl") or row["home"]
                out[(wk, away, home)] = float(row.get("sim_median") or row.get("sim_median_raw"))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def build_scan_rows(
    *,
    season: int = 2026,
    history: dict[str, list[dict[str, Any]]] | None = None,
    sim_by_match: dict[tuple[int, str, str], float] | None = None,
) -> list[ScanRow]:
    history = history or load_history()
    sim_by_match = sim_by_match or {}
    sched = load_schedules([season])
    sched = sched[pd.to_numeric(sched["week"], errors="coerce").notna()].copy()
    sched = sched[sched["home_score"].notna() & sched["away_score"].notna()]
    catalog = build_nfl_event_catalog()
    eid_map = match_event_ids_to_schedule(sched, catalog, history)

    rows: list[ScanRow] = []
    for _, srow in sched.iterrows():
        away = normalize_team(str(srow["away_team"]), "nfl") or ""
        home = normalize_team(str(srow["home_team"]), "nfl") or ""
        week = int(srow["week"])
        key = (week, away, home)
        eid = eid_map.get(key)
        if not eid:
            continue
        kickoff = _parse_kickoff(srow)
        final_total = float(srow["away_score"]) + float(srow["home_score"])
        over_samples = [
            s
            for s in samples_for(eid, "totals", "over", history=history)
            if s.get("book") == "pinnacle"
        ]
        if not over_samples:
            continue
        close_o = closing_sample(eid, "totals", "over", kickoff=kickoff, history=history)
        close_u = closing_sample(eid, "totals", "under", kickoff=kickoff, history=history)
        if not close_o:
            continue
        close_line = float(close_o["line"])
        close_op = int(float(close_o["price"]))
        close_up = int(float(close_u["price"])) if close_u else None

        open_o = opening_sample(eid, "totals", "over", history=history)
        open_line = float(open_o["line"]) if open_o else None

        wind = srow.get("wind")
        roof = srow.get("roof")
        try:
            wind_f = float(wind) if wind is not None and not (isinstance(wind, float) and math.isnan(wind)) else None
        except (TypeError, ValueError):
            wind_f = None
        roof_s = str(roof) if roof is not None and str(roof) != "nan" else None

        ctx = GameContext(
            season=season,
            week=week,
            away=away,
            home=home,
            event_id=eid,
            kickoff=kickoff,
            final_total=final_total,
            spread_line=float(srow["spread_line"]) if pd.notna(srow.get("spread_line")) else None,
            wind=wind_f,
            roof=roof_s,
        )
        sim_med = sim_by_match.get(key)

        sorted_scans = sorted(over_samples, key=lambda s: str(s.get("ts") or ""))
        if kickoff:
            sorted_scans = [
                s for s in sorted_scans if (_parse_ts(s.get("ts")) or kickoff) <= kickoff
            ]
        if len(sorted_scans) < 2:
            continue
        # Treat every sample except the last pre-kick snapshot as an early scan.
        for i, scan in enumerate(sorted_scans[:-1]):
            ts = _parse_ts(scan.get("ts"))
            prev = sorted_scans[i - 1] if i > 0 else None
            scan_line = float(scan["line"])
            scan_op = int(float(scan["price"]))
            under_at = _under_sample_at(history, eid, ts or datetime.now(timezone.utc))
            scan_up = int(float(under_at["price"])) if under_at else None
            hrs = None
            if kickoff and ts:
                hrs = (kickoff - ts).total_seconds() / 3600.0
            bf = _price_at(
                samples_for(eid, "totals", "over", history=history),
                ts or datetime.now(timezone.utc),
                "betfair_ex_eu",
            )
            bf_line = float(bf["line"]) if bf else None
            rows.append(
                ScanRow(
                    game=ctx,
                    scan_ts=str(scan.get("ts")),
                    hours_before_kick=round(hrs, 2) if hrs is not None else None,
                    scan_line=scan_line,
                    scan_over_price=scan_op,
                    scan_under_price=scan_up,
                    close_line=close_line,
                    close_over_price=close_op,
                    close_under_price=close_up,
                    side="",  # filled per signal
                    signal="",
                    betfair_line=bf_line,
                    open_line=open_line,
                    sim_median_cal=sim_med,
                    wind=wind_f,
                    roof=roof_s,
                    meta={
                        "prev_line": float(prev["line"]) if prev else None,
                        "scan_idx": i,
                    },
                )
            )
    return rows


def _attach_side(row: ScanRow, side: str, signal: str) -> ScanRow:
    row.side = side
    row.signal = signal
    return row


def signal_generators() -> dict[str, Callable[[ScanRow], str | None]]:
    """Return side (over/under) or None if signal does not fire."""

    def stale_betfair_05(r: ScanRow) -> str | None:
        if r.betfair_line is None:
            return None
        gap = r.betfair_line - r.scan_line
        if abs(gap) < 0.5:
            return None
        # Fade the outlier vs Pinnacle (bet toward Pinnacle / expected close)
        return "under" if gap > 0 else "over"

    def stale_betfair_10(r: ScanRow) -> str | None:
        if r.betfair_line is None:
            return None
        gap = r.betfair_line - r.scan_line
        if abs(gap) < 1.0:
            return None
        return "under" if gap > 0 else "over"

    def momentum_follow(r: ScanRow) -> str | None:
        if r.open_line is None:
            return None
        move = r.scan_line - r.open_line
        if abs(move) < 0.5:
            return None
        return "over" if move > 0 else "under"

    def momentum_fade(r: ScanRow) -> str | None:
        if r.open_line is None:
            return None
        move = r.scan_line - r.open_line
        if abs(move) < 0.5:
            return None
        return "under" if move > 0 else "over"

    def sim_vs_line_move(r: ScanRow) -> str | None:
        if r.sim_median_cal is None:
            return None
        edge = r.sim_median_cal - r.scan_line
        if abs(edge) < 1.0:
            return None
        return "over" if edge > 0 else "under"

    def weather_wind_over(r: ScanRow) -> str | None:
        if r.roof and str(r.roof).lower() in ("dome", "closed", "indoors"):
            return None
        if r.wind is None or r.wind < 12:
            return None
        return "under"

    def key_cross_up(r: ScanRow) -> str | None:
        prev = r.meta.get("prev_line")
        if prev is None:
            return None
        for k in KEY_TOTALS:
            if prev < k <= r.scan_line:
                return "over"
        return None

    def key_cross_down(r: ScanRow) -> str | None:
        prev = r.meta.get("prev_line")
        if prev is None:
            return None
        for k in KEY_TOTALS:
            if prev > k >= r.scan_line:
                return "under"
        return None

    return {
        "betfair_gap_0.5_fade": stale_betfair_05,
        "betfair_gap_1.0_fade": stale_betfair_10,
        "pinnacle_momentum_follow": momentum_follow,
        "pinnacle_momentum_fade": momentum_fade,
        "sim_projection_vs_scan_line": sim_vs_line_move,
        "wind12_under": weather_wind_over,
        "key_number_cross_up_over": key_cross_up,
        "key_number_cross_down_under": key_cross_down,
    }


def breakdown_by_week(rows: list[ScanRow]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[ScanRow]] = defaultdict(list)
    for r in rows:
        buckets[str(r.game.week)].append(r)
    return {w: evaluate_rows(v) for w, v in sorted(buckets.items(), key=lambda x: int(x[0]))}


def breakdown_by_side(rows: list[ScanRow]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[ScanRow]] = defaultdict(list)
    for r in rows:
        buckets[r.side].append(r)
    return {s: evaluate_rows(v) for s, v in sorted(buckets.items())}


def evaluate_rows(rows: list[ScanRow]) -> dict[str, Any]:
    if not rows:
        return {}
    out: dict[str, Any] = {}
    n = len(rows)
    beat_pts = sum(1 for r in rows if (r.meta.get("clv_points") or 0) > 0)
    clv_pts = [r.meta.get("clv_points") for r in rows if r.meta.get("clv_points") is not None]
    clv_pr = [r.meta.get("clv_prob") for r in rows if r.meta.get("clv_prob") is not None]
    w = sum(1 for r in rows if r.meta.get("result") == "W")
    l = sum(1 for r in rows if r.meta.get("result") == "L")
    p = sum(1 for r in rows if r.meta.get("result") == "P")
    u_scan = sum(float(r.meta.get("units_scan") or 0) for r in rows)
    u110 = sum(float(r.meta.get("units_110") or 0) for r in rows)
    out.update(
        {
            "n_plays": n,
            "pct_beat_close_points": round(100.0 * beat_pts / n, 1),
            "avg_clv_points": round(sum(clv_pts) / len(clv_pts), 3) if clv_pts else None,
            "avg_clv_prob": round(sum(clv_pr) / len(clv_pr), 4) if clv_pr else None,
            "record_final": f"{w}-{l}-{p}",
            "units_at_scan_price": round(u_scan, 2),
            "units_at_110": round(u110, 2),
            "meaningful": n >= MIN_MEANINGFUL,
        }
    )
    return out


def _fill_bet_metrics(row: ScanRow) -> None:
    side = row.side
    price = row.scan_over_price if side == "over" else (row.scan_under_price or -110)
    row.meta["clv_points"] = clv_points("totals", side, row.scan_line, row.close_line)
    if abs(row.scan_line - row.close_line) < 1e-6:
        close_p = row.close_over_price if side == "over" else (row.close_under_price or -110)
        row.meta["clv_prob"] = clv_prob(price, close_p)
    else:
        row.meta["clv_prob"] = None
    res = _grade(side, row.scan_line, row.game.final_total)
    row.meta["result"] = res
    row.meta["units_scan"] = _units(res, price)
    row.meta["units_110"] = _units(res, -110)


def run_signal_backtests(scan_rows: list[ScanRow]) -> dict[str, Any]:
    gens = signal_generators()
    results: dict[str, Any] = {}
    for name, fn in gens.items():
        fired: list[ScanRow] = []
        for base in scan_rows:
            side = fn(base)
            if side is None:
                continue
            import copy

            row = copy.copy(base)
            _attach_side(row, side, name)
            _fill_bet_metrics(row)
            fired.append(row)
        results[name] = evaluate_rows(fired)
    return results


def walk_forward_combined(
    scan_rows: list[ScanRow],
    *,
    min_train: int = 25,
) -> tuple[dict[str, Any], list[ScanRow]]:
    """Momentum follow when sim agrees; walk-forward gate on prior combined CLV only."""
    ordered = sorted(scan_rows, key=lambda r: (r.game.week, r.scan_ts, r.game.away))
    fired: list[ScanRow] = []
    train_clv: list[float] = []

    mom_fn = signal_generators()["pinnacle_momentum_follow"]
    sim_fn = signal_generators()["sim_projection_vs_scan_line"]

    for row in ordered:
        mom = mom_fn(row)
        sim = sim_fn(row)
        if not (mom and sim and mom == sim):
            continue
        import copy

        bet = copy.copy(row)
        _attach_side(bet, mom, "combined_momentum_plus_sim")
        _fill_bet_metrics(bet)
        clv = bet.meta.get("clv_points")
        if len(train_clv) >= min_train:
            avg = sum(train_clv) / len(train_clv)
            if avg > 0:
                fired.append(bet)
        if clv is not None:
            train_clv.append(float(clv))
    return evaluate_rows(fired), fired


def combined_without_gate(scan_rows: list[ScanRow]) -> tuple[dict[str, Any], list[ScanRow]]:
    """Same rule without walk-forward gate (for comparison)."""
    mom_fn = signal_generators()["pinnacle_momentum_follow"]
    sim_fn = signal_generators()["sim_projection_vs_scan_line"]
    fired: list[ScanRow] = []
    import copy

    for row in scan_rows:
        mom = mom_fn(row)
        sim = sim_fn(row)
        if mom and sim and mom == sim:
            bet = copy.copy(row)
            _attach_side(bet, mom, "combined_momentum_plus_sim_ungated")
            _fill_bet_metrics(bet)
            fired.append(bet)
    return evaluate_rows(fired), fired


def coverage_report(
    *,
    season: int = 2026,
    history: dict[str, list[dict[str, Any]]] | None = None,
    scan_rows: list[ScanRow] | None = None,
) -> dict[str, Any]:
    history = history or load_history()
    sched = load_schedules([season])
    completed = sched[sched["home_score"].notna()]
    catalog = build_nfl_event_catalog()
    eid_map = match_event_ids_to_schedule(completed, catalog, history)

    books = defaultdict(int)
    for key, samples in history.items():
        if "|totals|" not in key:
            continue
        for s in samples:
            books[s.get("book", "?")] += 1

    games_with_scans = len({(r.game.week, r.game.away, r.game.home) for r in (scan_rows or [])})
    return {
        "line_history_path": "data/line_history.json",
        "snapshot_books_in_totals_history": dict(books),
        "sharp_only_recording": True,
        "soft_retail_books_stored": False,
        "note_soft_books": (
            "record_snapshot() uses sharp_only=True; US retail books are not in line_history. "
            "Committed totals history on main is Pinnacle-only (no Betfair/retail series)."
        ),
        "completed_nfl_games_2026": int(len(completed)),
        "games_with_event_id_match": len(eid_map),
        "games_with_multiple_pin_scans": games_with_scans,
        "splits_historical": False,
        "splits_note": "Action Network splits are live-fetch only; not archived per scan in repo.",
        "injuries_stored": False,
        "weather_source": "nflverse schedules (wind, roof) for matched games",
        "team_totals_stored": False,
        "first_half_totals_stored": False,
    }


def rows_to_csv_dicts(rows: list[ScanRow]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        out.append(
            {
                "season": r.game.season,
                "week": r.game.week,
                "away": r.game.away,
                "home": r.game.home,
                "event_id": r.game.event_id,
                "scan_ts": r.scan_ts,
                "hours_before_kick": r.hours_before_kick,
                "signal": r.signal,
                "side": r.side,
                "scan_line": r.scan_line,
                "scan_price": r.scan_over_price if r.side == "over" else r.scan_under_price,
                "close_line": r.close_line,
                "close_over_price": r.close_over_price,
                "final_total": r.game.final_total,
                "clv_points": r.meta.get("clv_points"),
                "clv_prob": r.meta.get("clv_prob"),
                "result_final": r.meta.get("result"),
                "units_scan": r.meta.get("units_scan"),
                "units_110": r.meta.get("units_110"),
                "betfair_line_at_scan": r.betfair_line,
                "open_line": r.open_line,
                "sim_median_cal": r.sim_median_cal,
                "wind": r.wind,
                "roof": r.roof,
            }
        )
    return out


def supplement_jason_csv_scans(csv_path: Path) -> dict[str, Any]:
    """Single scan per game from Jason CSV (ledger-timed market_total vs pinnacle close)."""
    if not csv_path.exists():
        return {"available": False}
    games = load_games_from_csv(csv_path)
    games = append_completed_from_schedules(games, season=2026)
    rows: list[ScanRow] = []
    for g in games:
        if g.scan_line is None:
            continue
        ctx = GameContext(
            season=g.season,
            week=g.week,
            away=g.away,
            home=g.home,
            event_id="",
            kickoff=_parse_ts(g.kickoff_et),
            final_total=g.final_total,
            spread_line=None,
            wind=None,
            roof=None,
        )
        side = "over" if g.scan_line < g.close_line else "under"
        # CLV play: took the side that had the better number vs close
        if g.scan_line == g.close_line:
            continue
        side = "over" if g.scan_line < g.close_line else "under"
        sr = ScanRow(
            game=ctx,
            scan_ts=str(g.kickoff_et),
            hours_before_kick=None,
            scan_line=g.scan_line,
            scan_over_price=g.scan_price or -110,
            scan_under_price=None,
            close_line=g.close_line,
            close_over_price=g.close_price or -110,
            close_under_price=None,
            side=side,
            signal="csv_scan_beat_close_side",
            betfair_line=None,
            open_line=None,
            sim_median_cal=g.old_model_total,
            wind=None,
            roof=None,
        )
        _fill_bet_metrics(sr)
        rows.append(sr)
    ev = evaluate_rows(rows)
    return {"available": True, "n_games": len(games), "n_plays": len(rows), **ev}
