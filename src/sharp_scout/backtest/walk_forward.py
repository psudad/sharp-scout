"""Walk-forward backtesting — validate a model change before trusting it live.

Walk-forward means: for each week in chronological order, we *only* use information from
prior weeks to calibrate/decide, then grade on the current week. This avoids look-ahead
bias that makes naive backtests look better than reality.

The engine is deliberately data-driven so it runs offline and is unit-testable: it consumes
a list of graded prediction records and does not itself call any paid API. A record is::

    {
      "season": 2025, "week": 3,
      "p_true": 0.58,          # model probability for the side taken
      "price": -110,           # American odds actually available
      "outcome": "win",        # win | loss | push
      "edge": 0.04,            # optional, for filtering
      "clv_prob": 0.012,       # optional, tracked if present
    }

Feed it from the ledger (:func:`records_from_ledger`) or from a historical dataset built
with nflverse play-by-play + The Odds API historical endpoint.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from sharp_scout.analysis.calibration import (
    brier_score,
    collect_prediction_outcomes,
    fit_calibrator,
    calibrator_from_spec,
)
from sharp_scout.ledger.tracker import american_profit

logger = logging.getLogger(__name__)


def records_from_ledger(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Build backtest records from settled side plays in the ledger."""
    recs: list[dict[str, Any]] = []
    for p in ledger.get("plays") or []:
        if p.get("play_type") == "prop" or str(p.get("market") or "").startswith("player_"):
            continue
        if p.get("status") not in ("win", "loss", "push"):
            continue
        recs.append(
            {
                "season": p.get("season"),
                "week": p.get("week"),
                "p_true": p.get("p_true"),
                "price": p.get("price") if p.get("price") is not None else -110,
                "outcome": p.get("status"),
                "edge": p.get("edge"),
                "clv_prob": p.get("clv_prob"),
                "units": p.get("units") or 1.0,
            }
        )
    return recs


def _week_key(rec: dict[str, Any]) -> tuple[int, int]:
    return (int(rec.get("season") or 0), int(rec.get("week") or 0))


def _grade_units(rec: dict[str, Any]) -> float:
    units = float(rec.get("units") or 1.0)
    outcome = rec.get("outcome")
    if outcome == "win":
        return american_profit(units, float(rec.get("price") or -110))
    if outcome == "loss":
        return -units
    return 0.0


def walk_forward(
    records: list[dict[str, Any]],
    *,
    edge_threshold: float = 0.0,
    min_train: int = 20,
    decide: Callable[[dict[str, Any], Callable[[float], float]], bool] | None = None,
) -> dict[str, Any]:
    """Run a walk-forward backtest over chronologically ordered weekly records.

    For each week: fit a calibrator on all *prior* decided records, apply it, keep bets
    whose (calibrated) edge clears ``edge_threshold``, then grade. Returns per-week and
    cumulative metrics (units, ROI, hit rate, Brier, CLV).
    """
    weeks = sorted({_week_key(r) for r in records if r.get("p_true") is not None})
    by_week: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for r in records:
        if r.get("p_true") is None:
            continue
        by_week.setdefault(_week_key(r), []).append(r)

    history: list[dict[str, Any]] = []
    week_reports: list[dict[str, Any]] = []
    cum_units = 0.0
    cum_staked = 0.0
    cum_wins = cum_losses = cum_pushes = 0
    all_graded_pairs: list[tuple[float, int]] = []

    for wk in weeks:
        train = [h for h in history if h.get("outcome") in ("win", "loss")]
        if len(train) >= min_train:
            spec = fit_calibrator([(float(h["p_true"]), 1 if h["outcome"] == "win" else 0) for h in train])
        else:
            spec = {"method": "identity", "n": len(train)}
        calibrate = calibrator_from_spec(spec)

        wins = losses = pushes = 0
        units = 0.0
        staked = 0.0
        bets = 0
        for rec in by_week.get(wk, []):
            p_cal = calibrate(float(rec["p_true"]))
            if decide is not None:
                take = decide(rec, calibrate)
            else:
                # Recompute edge with the calibrated probability if we have a price.
                price = float(rec.get("price") or -110)
                dec = 1 + (price / 100.0 if price > 0 else 100.0 / abs(price))
                cal_edge = p_cal * dec - 1.0
                take = cal_edge >= edge_threshold
            if not take:
                continue
            bets += 1
            u = float(rec.get("units") or 1.0)
            staked += u
            units += _grade_units(rec)
            outcome = rec.get("outcome")
            if outcome == "win":
                wins += 1
                all_graded_pairs.append((float(rec["p_true"]), 1))
            elif outcome == "loss":
                losses += 1
                all_graded_pairs.append((float(rec["p_true"]), 0))
            else:
                pushes += 1

        decided = wins + losses
        week_reports.append(
            {
                "season": wk[0],
                "week": wk[1],
                "bets": bets,
                "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
                "win_pct": round(wins / decided, 3) if decided else None,
                "units": round(units, 3),
                "roi": round(units / staked, 3) if staked else None,
                "calibrator": spec.get("method"),
            }
        )
        cum_units += units
        cum_staked += staked
        cum_wins += wins
        cum_losses += losses
        cum_pushes += pushes
        # Only past weeks inform future calibration (walk-forward).
        history.extend(by_week.get(wk, []))

    decided = cum_wins + cum_losses
    return {
        "n_records": len(records),
        "n_weeks": len(weeks),
        "record": f"{cum_wins}-{cum_losses}" + (f"-{cum_pushes}" if cum_pushes else ""),
        "win_pct": round(cum_wins / decided, 3) if decided else None,
        "units": round(cum_units, 3),
        "staked": round(cum_staked, 3),
        "roi": round(cum_units / cum_staked, 3) if cum_staked else None,
        "brier": brier_score(all_graded_pairs),
        "avg_clv_prob": _avg_clv(records),
        "weeks": week_reports,
    }


def _avg_clv(records: list[dict[str, Any]]) -> float | None:
    vals = [float(r["clv_prob"]) for r in records if r.get("clv_prob") is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def backtest_from_ledger(ledger: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Convenience: walk-forward over the ledger's own settled history."""
    _ = collect_prediction_outcomes  # keep import used for parity/testing
    return walk_forward(records_from_ledger(ledger), **kwargs)
