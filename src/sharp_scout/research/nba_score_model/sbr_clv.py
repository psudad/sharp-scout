"""CLV / opener tests on SBR games with true open vs close (research)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sharp_scout.research.nba_score_model.evaluate import GamePred


SBR_EVAL_SEASONS = tuple(f"{y}-{str(y+1)[-2:]}" for y in range(2010, 2021))


def _open_margin(p: GamePred) -> float:
    sp = p.open_spread_home if p.open_spread_home is not None else p.close_spread_home
    return -float(sp)


def _close_margin(p: GamePred) -> float:
    return -p.close_spread_home


def _filter_sbr(preds: list[GamePred]) -> list[GamePred]:
    return [
        p
        for p in preds
        if p.source == "sbr"
        and p.season in SBR_EVAL_SEASONS
        and p.open_spread_home is not None
    ]


def ats_vs_opener(preds: list[GamePred], min_edge: float) -> dict[str, Any]:
    wins = losses = pushes = 0
    for p in preds:
        open_m = _open_margin(p)
        edge = p.proj_margin - open_m
        if abs(edge) < min_edge:
            continue
        pick_home = edge > 0
        open_sp = float(p.open_spread_home or p.close_spread_home)
        result = p.act_margin + open_sp
        if abs(result) < 0.5:
            pushes += 1
            continue
        if pick_home == (result > 0):
            wins += 1
        else:
            losses += 1
    units = wins * (100 / 110) - losses
    return {"n": wins + losses + pushes, "record": f"{wins}-{losses}-{pushes}", "units_at_110": round(units, 2)}


def line_move_clv(preds: list[GamePred], *, min_model_edge: float = 1.0) -> dict[str, Any]:
    """Does model-vs-open disagreement predict close moving toward the model?"""
    rows = _filter_sbr(preds)
    if not rows:
        return {"n": 0, "note": "no_sbr_preds"}
    hits = n = 0
    pairs: list[tuple[float, float]] = []
    for p in rows:
        if p.open_spread_home is None:
            continue
        open_m = _open_margin(p)
        close_m = _close_margin(p)
        move = close_m - open_m
        model_edge = p.proj_margin - open_m
        if abs(model_edge) < min_model_edge:
            continue
        n += 1
        if (model_edge > 0) == (move > 0):
            hits += 1
        pairs.append((model_edge, move))

    def corr() -> float | None:
        if len(pairs) < 50:
            return None
        xs = [a for a, _ in pairs]
        ys = [b for _, b in pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        num = sum((x - mx) * (y - my) for x, y in pairs)
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        return round(num / den, 3) if den else None

    with_real_open = [p for p in rows if abs(p.close_spread_home - float(p.open_spread_home)) >= 0.5]
    return {
        "seasons": list(SBR_EVAL_SEASONS),
        "n_sbr_games": len(rows),
        "n_with_open_close_diff_ge_half": len(with_real_open),
        "line_move_hit_rate_ge1pt_model_edge": round(hits / n, 3) if n else None,
        "line_move_n": n,
        "line_move_corr": corr(),
        "ats_opener_ge1": ats_vs_opener(rows, 1.0),
        "ats_opener_ge2": ats_vs_opener(rows, 2.0),
        "ats_opener_ge3": ats_vs_opener(rows, 3.0),
        "audit_note": (
            "Uses SBR home_open_spread vs home_close_spread; grades ATS vs opener spread. "
            "Walk-forward model from full history; no close line in projection."
        ),
    }
