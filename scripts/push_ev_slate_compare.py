#!/usr/bin/env python3
"""Compare push-aware EV across pre-#127, #127, and conditional-anchoring fixes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.ledger.tracker import load_ledger  # noqa: E402
from sharp_scout.phase2.monte_carlo import (  # noqa: E402
    _is_whole,
    p_push_for_market,
    simulate_game,
)
from sharp_scout.phase3.market import anchor_probability  # noqa: E402
from sharp_scout.sports import get_sport  # noqa: E402
from sharp_scout.utils.odds import (  # noqa: E402
    expected_value,
    expected_value_whole_line_cond,
    expected_value_with_push,
    marginal_win_prob,
    win_prob_to_conditional,
)


def _mus(model_spread: float, model_total: float) -> tuple[float, float]:
    away = (model_total + model_spread) / 2.0
    home = model_total - away
    return home, away


def _ev_pre127(p_true_marg: float, price: float, p_push: float) -> float:
    return expected_value(p_true_marg, price) + p_push


def _ev_pr127(market: str, side: str, line: float | None, p_true_marg: float, price: float, p_push: float) -> float:
    if market == "spreads" and _is_whole(line) and side == "home":
        return expected_value(p_true_marg, price)
    return expected_value_with_push(p_true_marg, price, p_push)


def _ev_symmetric_fix(
    p_model: float,
    p_fair: float | None,
    price: float,
    p_push: float,
    *,
    k: float,
    tilt_cap: float | None,
) -> tuple[float, float]:
    p_cond = win_prob_to_conditional(p_model, p_push)
    if p_fair is not None and k < 1.0:
        p_cond = anchor_probability(p_cond, p_fair, k, tilt_cap)
    p_marg = marginal_win_prob(p_cond, p_push)
    ev = expected_value_whole_line_cond(p_cond, price, p_push)
    return p_marg, ev


def main() -> None:
    cfg = get_sport("ncaaf")
    k = cfg.anchor_k_spread
    tilt = cfg.anchor_tilt_cap
    ledger = load_ledger(ROOT / "data/ncaaf_ledger.json")
    rows: list[dict] = []
    for p in ledger.get("plays") or []:
        if (p.get("status") or "") != "pending":
            continue
        if p.get("sport") not in (None, "ncaaf"):
            continue
        market = p.get("market")
        line = p.get("line")
        if market not in ("spreads", "totals") or not _is_whole(line):
            continue
        p_model = p.get("p_model")
        if p_model is None:
            continue
        price = float(p.get("price") or -110)
        side = p.get("side")
        p_fair = p.get("p_fair")
        pf = float(p_fair) if p_fair is not None else None
        ms, mt = p.get("model_spread"), p.get("model_total")
        mu_h, mu_a = _mus(float(ms), float(mt))
        sk = [float(line), float(line) + 0.5, float(line) - 0.5]
        sim = simulate_game(
            p.get("home_team") or "HOME",
            p.get("away_team") or "AWAY",
            mu_h,
            mu_a,
            n_sims=20_000,
            spread_keys=sk if market == "spreads" else None,
            total_keys=sk if market == "totals" else None,
            sport="ncaaf",
            seed=11,
        )
        p_push = p_push_for_market(sim, market, side, float(line), sport="ncaaf")
        k_use = k if market == "spreads" else cfg.anchor_k_total
        cap = tilt if market == "spreads" or cfg.anchor_tilt_cap_totals else None
        p_true_pre127 = (
            anchor_probability(float(p_model), pf, k_use, cap) if pf is not None else float(p_model)
        )
        ev_pre127 = _ev_pre127(p_true_pre127, price, p_push)
        ev_pr127 = _ev_pr127(market, side, line, p_true_pre127, price, p_push)
        _, ev_fix = _ev_symmetric_fix(
            float(p_model), pf, price, p_push, k=k_use, tilt_cap=cap
        )
        rows.append(
            {
                "game": f"{p.get('away_team')} @ {p.get('home_team')}",
                "pick": f"{side} {line} ({market}) @ {p.get('book')}",
                "ev_pre_127": f"{ev_pre127 * 100:.2f}%",
                "ev_pr_127": f"{ev_pr127 * 100:.2f}%",
                "ev_symmetric_fix": f"{ev_fix * 100:.2f}%",
                "cert_pre_127": ev_pre127 >= 0.04,
                "cert_pr_127": ev_pr127 >= 0.04,
                "cert_symmetric_fix": ev_fix >= 0.04,
            }
        )

    print(json.dumps(rows, indent=2))
    print(f"\n{len(rows)} pending whole-number play(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
