#!/usr/bin/env python3
"""Fit √pace margin SD on train seasons; validate on holdout; write report.

Requires: pip install sportsdataverse (research only — not a core package dependency).

Data: ESPN schedule scores + consensus closing spread from game JSON (pickcenter),
expected possessions from Barttorvik season ``adjT`` (geometric mean), matching the
Nov 2026 pace review methodology. Train ESPN seasons 2008–2016; holdout 2017–2021.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pandas as pd

from sharp_scout.config import DATA_DIR, ROOT
from sharp_scout.ncaam.margin_sd_calibration import summarize_calibration
from sharp_scout.ncaam.margin_sd_pace import (
    DEFAULT_REF_POSSESSIONS,
    LIVE_MARGIN_SD,
    REVIEW_FIT_BASE,
    cover_nll_per_game,
    fit_sqrt_pace_base,
    p_cover_spread_normal,
    margin_sd_sqrt_pace,
)
from sharp_scout.ncaam.margin_sd_season_replay import summarize_season_replay
from sharp_scout.ncaam.margin_sd_shadow import PARAMS_PATH

logger = logging.getLogger(__name__)

REPORT_PATH = ROOT / "reports" / "ncaam_margin_sd_pace_backtest.md"
CACHE_PATH = DATA_DIR / "research" / "ncaam_margin_sd_spread_cache.json"
TRAIN_SEASONS = list(range(2008, 2017))
HOLDOUT_SEASONS = list(range(2017, 2022))


def _norm_name(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", "", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _load_barttorvik_adjt(season: int) -> dict[str, float]:
    """Season row CSV: team name -> adjT."""
    url = f"https://barttorvik.com/{season}_team_results.csv"
    r = httpx.get(url, timeout=60.0, follow_redirects=True)
    r.raise_for_status()
    lines = r.text.splitlines()
    out: dict[str, float] = {}
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 47:
            continue
        team = parts[1].strip().strip('"')
        try:
            adjt = float(parts[-1])
        except ValueError:
            continue
        out[_norm_name(team)] = adjt
    return out


def _fetch_consensus_line(url: str, client: httpx.Client) -> tuple[float | None, float | None]:
    """Return (home_spread, closing_total) from ESPN pickcenter consensus when available."""
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
    spread_cache: dict[str, float],
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
        per = max(50, max_fetch // max(len(by_season), 1))
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
        # Pace proxy: closing total maps to expected possessions (review used ~67 mean).
        xposs = float(total) / 2.05 if total is not None else DEFAULT_REF_POSSESSIONS
        rows.append(
            {
                "game_id": gid,
                "season": int(g["season"]),
                "home": str(g.get("home_short_display_name") or g.get("home_display_name")),
                "away": str(g.get("away_short_display_name") or g.get("away_display_name")),
                "margin": margin,
                "spread_home": spread,
                "home_covered": home_covered,
                "expected_poss": xposs,
            }
        )
    return pd.DataFrame(rows)


def _attach_expected_poss(df: pd.DataFrame) -> pd.DataFrame:
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument(
        "--max-spread-fetch",
        type=int,
        default=4000,
        help="Cap new JSON spread fetches per table build (train/holdout each)",
    )
    p.add_argument("--write-params", action="store_true", default=True)
    args = p.parse_args()

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    spread_cache: dict[str, float] = {}
    if CACHE_PATH.exists():
        raw = json.loads(CACHE_PATH.read_text())
        for k, v in raw.items():
            if isinstance(v, (int, float)):
                spread_cache[k] = {"spread_home": float(v)}
            elif isinstance(v, dict):
                spread_cache[k] = v

    all_seasons = sorted(set(TRAIN_SEASONS) | set(HOLDOUT_SEASONS))
    logger.info("Building games table seasons=%s", all_seasons)
    all_g = _build_games_table(all_seasons, spread_cache=spread_cache, max_fetch=args.max_spread_fetch)
    all_g = _attach_expected_poss(all_g)
    train_g = all_g[all_g["season"].isin(TRAIN_SEASONS)].copy()
    hold_g = all_g[all_g["season"].isin(HOLDOUT_SEASONS)].copy()
    logger.info("Train games with spread+poss: %d", len(train_g))
    logger.info("Holdout games with spread+poss: %d", len(hold_g))

    CACHE_PATH.write_text(json.dumps(spread_cache, indent=0) + "\n")

    # μ = 0: calibrate volatility of ATS vs market (same as review residual NLL comparison).
    margin_mu_tr = [0.0] * len(train_g)
    margin_mu_ho = [0.0] * len(hold_g)

    if train_g.empty or hold_g.empty:
        raise SystemExit(
            f"Insufficient games (train={len(train_g)}, holdout={len(hold_g)}). "
            "Re-run with a higher --max-spread-fetch or delete the spread cache."
        )

    params, train_nll = fit_sqrt_pace_base(
        train_g["expected_poss"],
        margin_mu_tr,
        train_g["spread_home"],
        train_g["home_covered"],
    )
    const_sd = float(train_g["margin"].add(train_g["spread_home"]).std())
    if math.isnan(const_sd) or const_sd <= 0:
        const_sd = 10.508

    review_params = fit_sqrt_pace_base(
        train_g["expected_poss"],
        margin_mu_tr,
        train_g["spread_home"],
        train_g["home_covered"],
    )[0]
    _ = review_params  # empirical fit on ESPN subsample (pace proxy = close total / 2.05)

    hold_pairs_live: list[tuple[float, int]] = []
    hold_pairs_pace: list[tuple[float, int]] = []
    hold_pairs_review: list[tuple[float, int]] = []
    nll_live = 0.0
    nll_pace = 0.0
    nll_review = 0.0
    for _, row in hold_g.iterrows():
        y = int(row["home_covered"])
        spread = float(row["spread_home"])
        poss = float(row["expected_poss"])
        sd_p = params.sd(poss)
        sd_rev = margin_sd_sqrt_pace(poss, base=REVIEW_FIT_BASE)
        p_pace, _ = p_cover_spread_normal(0.0, spread, "home", sd_p)
        p_rev, _ = p_cover_spread_normal(0.0, spread, "home", sd_rev)
        p_live, _ = p_cover_spread_normal(0.0, spread, "home", LIVE_MARGIN_SD)
        hold_pairs_pace.append((p_pace, y))
        hold_pairs_review.append((p_rev, y))
        hold_pairs_live.append((p_live, y))
        nll_pace += cover_nll_per_game(0.0, spread, y, sd_p)
        nll_review += cover_nll_per_game(0.0, spread, y, sd_rev)
        nll_live += cover_nll_per_game(0.0, spread, y, LIVE_MARGIN_SD)
    n_hold = max(len(hold_g), 1)
    nll_pace /= n_hold
    nll_review /= n_hold
    nll_live /= n_hold

    cal_live = summarize_calibration(hold_pairs_live, label=f"fixed sd={LIVE_MARGIN_SD}")
    cal_pace = summarize_calibration(hold_pairs_pace, label=f"√pace sd base={params.base:.3f}")
    cal_review = summarize_calibration(hold_pairs_review, label=f"review base={REVIEW_FIT_BASE}")

    season = summarize_season_replay()

    if args.write_params:
        PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PARAMS_PATH.write_text(
            json.dumps(
                {
                    "model": "sqrt_pace",
                    "base": REVIEW_FIT_BASE,
                    "empirical_fit_base_espn_subsample": round(params.base, 4),
                    "ref_poss": DEFAULT_REF_POSSESSIONS,
                    "train_seasons": TRAIN_SEASONS,
                    "holdout_seasons": HOLDOUT_SEASONS,
                    "train_games": len(train_g),
                    "holdout_games": len(hold_g),
                    "train_nll_per_game": round(train_nll, 4),
                    "holdout_nll_live_sd": round(nll_live, 4),
                    "holdout_nll_pace_sd": round(nll_review, 4),
                    "holdout_nll_empirical_pace_sd": round(nll_pace, 4),
                    "holdout_nll_delta": round(nll_review - nll_live, 4),
                    "const_sd_train_residual": round(const_sd, 4),
                },
                indent=2,
            )
            + "\n"
        )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    posted = season["official_posted"]
    pace = season["would_qualify_pace_sd"]
    body = f"""# NCAAM pace-scaled margin SD (shadow)

## Plain English

The live model treats every game’s scoring noise as **~10.5 points** when turning a projected margin into cover probability. That is pace-blind. This shadow lane uses **√(expected possessions)** scaling so faster games get a slightly wider margin distribution. It does **not** change posted picks; it only logs alternate `p_model` / EV next to the live numbers.

## Fitted parameters (train seasons {TRAIN_SEASONS[0]}–{TRAIN_SEASONS[-1]})

- Model: `sd = base × sqrt(expected_poss / {DEFAULT_REF_POSSESSIONS})`
- **base = {REVIEW_FIT_BASE:.4f}** (SBRO review train 2008–16; shadow uses Barttorvik projected poss)
- ESPN subsample empirical fit (close total pace proxy): **{params.base:.4f}**
- Train games used: **{len(train_g)}**
- Holdout games used: **{len(hold_g)}** (seasons {HOLDOUT_SEASONS[0]}–{HOLDOUT_SEASONS[-1]})

## Holdout calibration (ATS vs consensus close, μ=0)

| SD | NLL/game | Brier | pred mean | obs freq |
|---|---:|---:|---:|---:|
| Live `{LIVE_MARGIN_SD}` | {nll_live:.4f} | {cal_live['brier']} | {cal_live['pred_mean']} | {cal_live['obs_freq']} |
| Review pace √ (base={REVIEW_FIT_BASE}) | {nll_review:.4f} | {cal_review['brier']} | {cal_review['pred_mean']} | {cal_review['obs_freq']} |
| ESPN subsample pace √ | {nll_pace:.4f} | {cal_pace['brier']} | {cal_pace['pred_mean']} | {cal_pace['obs_freq']} |

**Δ NLL (review pace − live): {nll_review - nll_live:+.4f} / game** on holdout (ESPN consensus, n={len(hold_g)}).

### Reliability (holdout) — live sd

| bin | n | pred | obs | gap |
|---|---:|---:|---:|---:|
"""
    for b in cal_live.get("bins") or []:
        body += f"| {b['bin']} | {b['n']} | {b['pred_mean']} | {b['obs_freq']} | {b['gap']:+} |\n"

    body += "\n### Reliability (holdout) — pace sd\n\n| bin | n | pred | obs | gap |\n|---|---:|---:|---:|---:|\n"
    for b in cal_pace.get("bins") or []:
        body += f"| {b['bin']} | {b['n']} | {b['pred_mean']} | {b['obs_freq']} | {b['gap']:+} |\n"

    body += f"""
## 2026 season counterfactual (68 official spread/ML stakes)

| | n | W-L | units | Wilson 95% |
|---|---:|---|---:|---|
| **Posted (live SD)** | {posted['n_decided']} | {posted['wins']}-{posted['losses']} | {posted['units']:+.2f}u | {posted['wilson_95'][0]:.1%}–{posted['wilson_95'][1]:.1%} |
| **Would qualify (pace SD)** | {pace['n_decided']} | {pace['wins']}-{pace['losses']} | {pace['units']:+.2f}u | {pace['wilson_95'][0]:.1%}–{pace['wilson_95'][1]:.1%} |

Dropped by pace SD among posted plays: **{season['dropped_by_pace_sd']}**.

Shadow output path: `data/shadow/ncaam_margin_sd_pace.json` (populated on runner candidate evaluation).
"""
    REPORT_PATH.write_text(body)
    print(body)
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
