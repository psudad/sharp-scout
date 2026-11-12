#!/usr/bin/env python3
"""Modern-era margin SD fit (train 2012–16); holdout 2017–21 (+ 2022+ check).

Compares constant vs sqrt(poss) vs linear(poss/ref) pace scaling. Writes shadow
params for the holdout winner. Requires: pip install sportsdataverse (research only).
"""

from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pandas as pd

from sharp_scout.config import DATA_DIR, ROOT
from sharp_scout.ncaam.margin_sd_calibration import summarize_calibration
from sharp_scout.ncaam.margin_sd_pace import (
    DEFAULT_REF_POSSESSIONS,
    LIVE_MARGIN_SD,
    PaceSdModel,
    PaceSdParams,
    cover_nll_per_game,
    fit_pace_sd_base,
    margin_sd_for_model,
    p_cover_spread_normal,
)
from sharp_scout.ncaam.margin_sd_season_replay import summarize_season_replay
from sharp_scout.ncaam.margin_sd_shadow import PARAMS_PATH

logger = logging.getLogger(__name__)

REPORT_PATH = ROOT / "reports/ncaam_margin_sd_pace_backtest.md"
CACHE_PATH = DATA_DIR / "research" / "ncaam_margin_sd_spread_cache.json"

# Modern-era train (per Nov 2026 review); primary holdout 2017–21.
TRAIN_SEASONS = list(range(2012, 2017))
HOLDOUT_SEASONS = list(range(2017, 2022))
EXTENDED_HOLDOUT_SEASONS = list(range(2022, 2027))

MODELS: list[PaceSdModel] = ["constant", "sqrt_pace", "linear_pace"]

# μ=0 spread-only calibration pushes unbounded toward ~13–14; cap at modern-era ~12
# (SBRO / ESPN 2017–21 review band) so shadow meaningfully differs from live 10.5.
MODERN_BASE_BOUNDS: tuple[float, float] = (9.0, 12.0)


def _fetch_consensus_line(url: str, client: httpx.Client) -> tuple[float | None, float | None]:
    if not url:
        return None, None
    try:
        j = client.get(url, timeout=25.0).json()
    except Exception:
        return None, None
    picks = j.get("pickcenter") or []
    ordered = sorted(
        picks,
        key=lambda r: 0 if "consensus" in str((r.get("provider") or {}).get("name", "")).lower() else 1,
    )
    for row in ordered:
        sp = row.get("spread")
        total = row.get("overUnder")
        if sp is not None:
            return float(sp), (float(total) if total is not None else None)
    return None, None


def _build_games_table(
    seasons: list[int],
    *,
    spread_cache: dict[str, dict],
    max_fetch: int | None,
) -> pd.DataFrame:
    from sportsdataverse.mbb import load_mbb_schedule

    sched = load_mbb_schedule(seasons=seasons, return_as_pandas=True)
    sched = sched[sched["status_type_name"] == "STATUS_FINAL"].copy()
    by_season: dict[int, list[tuple[str, str]]] = {}
    for _, g in sched.iterrows():
        gid = str(g["game_id"])
        if gid in spread_cache:
            continue
        json_url = g.get("game_json_url")
        if pd.notna(json_url):
            by_season.setdefault(int(g["season"]), []).append((gid, str(json_url)))
    pending: list[tuple[str, str]] = []
    if max_fetch is None:
        for items in by_season.values():
            pending.extend(items)
    else:
        per = max(80, max_fetch // max(len(by_season), 1))
        for s in sorted(by_season):
            pending.extend(by_season[s][:per])
            if len(pending) >= max_fetch:
                pending = pending[:max_fetch]
                break

    if pending:

        def _job(item: tuple[str, str]) -> tuple[str, dict[str, float] | None]:
            gid, url = item
            with httpx.Client() as client:
                spread, total = _fetch_consensus_line(url, client)
                if spread is None:
                    return gid, None
                payload: dict[str, float] = {"spread_home": float(spread)}
                if total is not None:
                    payload["closing_total"] = float(total)
                return gid, payload

        with ThreadPoolExecutor(max_workers=24) as pool:
            for fut in as_completed(pool.submit(_job, it) for it in pending):
                gid, payload = fut.result()
                if payload is not None:
                    spread_cache[gid] = payload

    rows: list[dict] = []
    for _, g in sched.iterrows():
        gid = str(g["game_id"])
        cached = spread_cache.get(gid)
        if not cached:
            continue
        spread = float(cached["spread_home"])
        hs, as_ = int(g["home_score"]), int(g["away_score"])
        margin = hs - as_
        home_covered = 1 if margin + spread > 0 else 0
        total = cached.get("closing_total")
        xposs = float(total) / 2.05 if total is not None else DEFAULT_REF_POSSESSIONS
        rows.append(
            {
                "game_id": gid,
                "season": int(g["season"]),
                "margin": margin,
                "spread_home": spread,
                "home_covered": home_covered,
                "expected_poss": xposs,
            }
        )
    return pd.DataFrame(rows)


def _evaluate_holdout(
    hold_g: pd.DataFrame,
    params: PaceSdParams,
) -> tuple[float, dict]:
    pairs: list[tuple[float, int]] = []
    nll = 0.0
    for _, row in hold_g.iterrows():
        y = int(row["home_covered"])
        spread = float(row["spread_home"])
        poss = float(row["expected_poss"])
        sd = params.sd(poss)
        p, _ = p_cover_spread_normal(0.0, spread, "home", sd)
        pairs.append((p, y))
        nll += cover_nll_per_game(0.0, spread, y, sd)
    n = max(len(hold_g), 1)
    cal = summarize_calibration(pairs, label=params.model)
    return nll / n, cal


def _load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    raw = json.loads(CACHE_PATH.read_text())
    out: dict[str, dict] = {}
    for k, v in raw.items():
        if isinstance(v, (int, float)):
            out[k] = {"spread_home": float(v)}
        elif isinstance(v, dict):
            out[k] = v
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--max-spread-fetch", type=int, default=6000)
    args = p.parse_args()

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    spread_cache = _load_cache()

    all_seasons = sorted(
        set(TRAIN_SEASONS) | set(HOLDOUT_SEASONS) | set(EXTENDED_HOLDOUT_SEASONS)
    )
    logger.info("Building games table seasons=%s", all_seasons)
    all_g = _build_games_table(all_seasons, spread_cache=spread_cache, max_fetch=args.max_spread_fetch)
    CACHE_PATH.write_text(json.dumps(spread_cache, indent=0) + "\n")

    train_g = all_g[all_g["season"].isin(TRAIN_SEASONS)].copy()
    hold_g = all_g[all_g["season"].isin(HOLDOUT_SEASONS)].copy()
    ext_g = all_g[all_g["season"].isin(EXTENDED_HOLDOUT_SEASONS)].copy()
    logger.info("Train=%d holdout=%d extended=%d", len(train_g), len(hold_g), len(ext_g))

    if train_g.empty or hold_g.empty:
        raise SystemExit(
            f"Insufficient games (train={len(train_g)}, holdout={len(hold_g)}). "
            "Re-run with higher --max-spread-fetch."
        )

    margin_mu = [0.0] * len(train_g)

    fits: dict[PaceSdModel, tuple[PaceSdParams, float]] = {}
    for m in MODELS:
        fits[m] = fit_pace_sd_base(
            m,
            train_g["expected_poss"],
            margin_mu,
            train_g["spread_home"],
            train_g["home_covered"],
            base_bounds=MODERN_BASE_BOUNDS,
        )
        logger.info("Train fit %s base=%.4f nll=%.4f", m, fits[m][0].base, fits[m][1])

    holdout_metrics: dict[PaceSdModel, dict] = {}
    for m in MODELS:
        nll, cal = _evaluate_holdout(hold_g, fits[m][0])
        holdout_metrics[m] = {"nll": nll, "brier": cal["brier"], "cal": cal}

    nll_live, cal_live = _evaluate_holdout(
        hold_g, PaceSdParams(model="constant", base=LIVE_MARGIN_SD)
    )

    winner = min(MODELS, key=lambda m: holdout_metrics[m]["nll"])
    winner_params = fits[winner][0]

    # Shadow uses modern-era winning fit (not live 10.5).
    PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARAMS_PATH.write_text(
        json.dumps(
            {
                "model": winner_params.model,
                "base": round(winner_params.base, 4),
                "ref_poss": DEFAULT_REF_POSSESSIONS,
                "train_seasons": TRAIN_SEASONS,
                "holdout_seasons": HOLDOUT_SEASONS,
                "train_games": len(train_g),
                "holdout_games": len(hold_g),
                "extended_holdout_games": len(ext_g),
                "fits_train_nll": {m: round(fits[m][1], 4) for m in MODELS},
                "fits_base": {m: round(fits[m][0].base, 4) for m in MODELS},
                "holdout_nll_live_sd": round(nll_live, 4),
                "holdout_brier_live_sd": cal_live["brier"],
                "holdout_comparison": {
                    m: {
                        "nll": round(holdout_metrics[m]["nll"], 4),
                        "brier": holdout_metrics[m]["brier"],
                        "delta_nll_vs_live": round(holdout_metrics[m]["nll"] - nll_live, 4),
                    }
                    for m in MODELS
                },
                "winner": winner,
                "live_margin_sd": LIVE_MARGIN_SD,
                "base_bounds": list(MODERN_BASE_BOUNDS),
            },
            indent=2,
        )
        + "\n"
    )

    ext_lines = ""
    if not ext_g.empty:
        nll_live_ext, _ = _evaluate_holdout(
            ext_g, PaceSdParams(model="constant", base=LIVE_MARGIN_SD)
        )
        ext_lines = "\n## Extended holdout (2022–26 ESPN subsample)\n\n| model | base | NLL/game | Δ vs live 10.5 |\n|---|---:|---:|---:|\n"
        ext_lines += f"| live 10.5 | — | {nll_live_ext:.4f} | +0.0000 |\n"
        for m in MODELS:
            nll_e, _ = _evaluate_holdout(ext_g, fits[m][0])
            ext_lines += (
                f"| {m} | {fits[m][0].base:.4f} | {nll_e:.4f} | {nll_e - nll_live_ext:+.4f} |\n"
            )
        ext_lines += f"\nGames: **{len(ext_g)}** (spread cache coverage; not full universe).\n"
    else:
        ext_lines = "\n## Extended holdout (2022+)\n\nNo cached ESPN consensus lines for 2022+ in this run.\n"

    season = summarize_season_replay()
    posted = season["official_posted"]
    pace = season["would_qualify_pace_sd"]
    win_cal = holdout_metrics[winner]["cal"]

    model_desc = {
        "constant": f"sd = base (no pace scaling)",
        "sqrt_pace": f"sd = base × sqrt(poss / {DEFAULT_REF_POSSESSIONS})",
        "linear_pace": f"sd = base × (poss / {DEFAULT_REF_POSSESSIONS})",
    }

    body = f"""# NCAAM pace-scaled margin SD (shadow)

## Plain English

Live NCAAM still uses a fixed **10.5**-point margin SD. Shadow fits train on **{TRAIN_SEASONS[0]}–{TRAIN_SEASONS[-1]}** with base in **{MODERN_BASE_BOUNDS[0]}–{MODERN_BASE_BOUNDS[1]}** (modern-era band; uncapped μ=0 fits drift to ~13–14 and no longer test the approved ~11–12 lift). Pace scaling compares constant vs √ vs linear. Logging only — no picks, stakes, or ledger changes.

## Modern-era fit (train {TRAIN_SEASONS[0]}–{TRAIN_SEASONS[-1]}, n={len(train_g)}, base ∈ {MODERN_BASE_BOUNDS})

| Model | Fitted base | Train NLL/game |
|---|---:|---:|
"""
    for m in MODELS:
        body += f"| {model_desc[m]} | **{fits[m][0].base:.4f}** | {fits[m][1]:.4f} |\n"

    body += f"""
## Holdout calibration (2017–21, n={len(hold_g)}, ESPN consensus, μ=0)

| Model | base | NLL/game | Brier | Δ NLL vs live 10.5 |
|---|---:|---:|---:|---:|
| Live **10.5** | — | {nll_live:.4f} | {cal_live['brier']} | — |
"""
    for m in MODELS:
        hm = holdout_metrics[m]
        body += (
            f"| {m} | {fits[m][0].base:.4f} | {hm['nll']:.4f} | {hm['brier']} | "
            f"{hm['nll'] - nll_live:+.4f} |\n"
        )

    body += f"""
**Shadow winner (lowest holdout NLL): `{winner}`** with base **{winner_params.base:.4f}**.

### Reliability — live sd 10.5

| bin | n | pred | obs | gap |
|---|---:|---:|---:|---:|
"""
    for b in cal_live.get("bins") or []:
        body += f"| {b['bin']} | {b['n']} | {b['pred_mean']} | {b['obs_freq']} | {b['gap']:+} |\n"

    body += f"""
### Reliability — shadow winner ({winner}, base={winner_params.base:.3f})

| bin | n | pred | obs | gap |
|---|---:|---:|---:|---:|
"""
    for b in win_cal.get("bins") or []:
        body += f"| {b['bin']} | {b['n']} | {b['pred_mean']} | {b['obs_freq']} | {b['gap']:+} |\n"

    body += ext_lines

    body += f"""
## 2026 season counterfactual (68 official staked plays)

| | n | W-L | units | Wilson 95% |
|---|---:|---|---:|---|
| **Posted (live SD 10.5)** | {posted['n_decided']} | {posted['wins']}-{posted['losses']} | {posted['units']:+.2f}u | {posted['wilson_95'][0]:.1%}–{posted['wilson_95'][1]:.1%} |
| **Would qualify (shadow {winner})** | {pace['n_decided']} | {pace['wins']}-{pace['losses']} | {pace['units']:+.2f}u | {pace['wilson_95'][0]:.1%}–{pace['wilson_95'][1]:.1%} |

Dropped among posted: **{season['dropped_by_pace_sd']}**.

Shadow JSON: `data/shadow/ncaam_margin_sd_pace.json` · Params: `data/shadow/ncaam_margin_sd_pace_params.json`
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(body)
    print(body)
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
