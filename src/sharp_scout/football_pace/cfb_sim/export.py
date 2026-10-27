"""Weekly CFB Monte Carlo slate export (2026-only, shadow)."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from sharp_scout.config import DATA_DIR
from sharp_scout.data.cfbfastr import cfb_rating_plays, load_cfb_pbp
from sharp_scout.data.espn_cfb import fetch_espn_cfb_injuries
from sharp_scout.football_pace.cfb_sim.adjustments import (
    MARGINAL_SIMS,
    build_adjusted_profiles,
    measure_all_impacts,
)
from sharp_scout.football_pace.cfb_sim.drives import load_drive_table, season_actual_scoring
from sharp_scout.football_pace.cfb_sim.profiles import build_profiles
from sharp_scout.football_pace.cfb_sim.simulate import N_SIMS_DEFAULT, SimSummary, simulate_matchup
from sharp_scout.football_pace.slate import ET, default_projection_window, kickoff_et_label, merge_slate

SHADOW_DIR = DATA_DIR / "shadow" / "football_pace"


def _slate_games(season: int = 2026) -> list:
    windows = default_projection_window()
    win = windows["ncaaf"]
    games = merge_slate("ncaaf", season, window=win)
    return games


def _kickoff_et_date(game) -> date | None:
    if not game.game_date:
        return None
    dt = game.game_date
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).date()


def _filter_kickoff_et_date(games: list, kickoff_et_date: date) -> list:
    return [g for g in games if _kickoff_et_date(g) == kickoff_et_date]


def _injuries_by_team() -> dict[str, list[dict]]:
    rows = fetch_espn_cfb_injuries()
    by: dict[str, list[dict]] = {}
    for r in rows:
        team = str(r.get("team") or "").strip()
        if not team:
            continue
        by.setdefault(team, []).append(r)
    return by


def _sim_row(prefix: str, sim: SimSummary) -> dict[str, Any]:
    return {
        f"{prefix}_home_median": round(sim.home_median, 1),
        f"{prefix}_away_median": round(sim.away_median, 1),
        f"{prefix}_total_median": round(sim.total_median, 1),
        f"{prefix}_margin_median": round(sim.margin_median, 1),
        f"{prefix}_home_win_pct": sim.home_win_pct,
        f"{prefix}_home_poss": sim.home_poss_mean,
        f"{prefix}_away_poss": sim.away_poss_mean,
        f"{prefix}_home_to": sim.home_to_mean,
        f"{prefix}_away_to": sim.away_to_mean,
    }


def run_week_simulation(
    *,
    season: int = 2026,
    n_sims: int = N_SIMS_DEFAULT,
    kickoff_et_date: date | None = None,
    file_tag: str | None = None,
) -> dict[str, Any]:
    drives = load_drive_table(season)
    pbp = load_cfb_pbp([season])
    rating_plays, _ = cfb_rating_plays(pbp) if not pbp.empty else (pd.DataFrame(), set())
    profiles = build_profiles(drives, rating_plays)
    actual = season_actual_scoring(drives)
    games = _slate_games(season)
    if kickoff_et_date is not None:
        games = _filter_kickoff_et_date(games, kickoff_et_date)
    injuries = _injuries_by_team()

    rows: list[dict[str, Any]] = []
    for g in games:
        if g.home in ("NAN", "nan") or g.away in ("NAN", "nan"):
            continue
        seed = hash(g.game_id) % 2**31
        base = simulate_matchup(g.home, g.away, profiles, n_sims=n_sims, seed=seed)
        bundle = build_adjusted_profiles(g.home, g.away, profiles, injuries)
        measure_all_impacts(
            g.home,
            g.away,
            profiles,
            injuries,
            bundle,
            seed=seed + 1,
            n_sims=min(MARGINAL_SIMS, max(1500, n_sims // 5)),
        )
        adj = simulate_matchup(
            g.home,
            g.away,
            profiles,
            home_profile=bundle.home,
            away_profile=bundle.away,
            n_sims=n_sims,
            seed=seed + 2,
        )

        spread = float(g.spread_home) if g.spread_home is not None else None
        total = float(g.total_line) if g.total_line is not None else None
        row: dict[str, Any] = {
            "game_id": g.game_id,
            "kickoff_et": None,
            "away": g.away,
            "home": g.home,
            "market_spread_home": spread,
            "market_total": total,
            **_sim_row("base", base),
            **_sim_row("adj", adj),
            "base_main_driver": base.main_driver,
            "adj_gap_total": round(adj.total_median - total, 1) if total is not None else None,
            "adj_gap_margin": round(adj.margin_median + spread, 1) if spread is not None else None,
            "base_gap_total": round(base.total_median - total, 1) if total is not None else None,
            "base_gap_margin": round(base.margin_median + spread, 1) if spread is not None else None,
            "comparison_total_delta": round(adj.total_median - base.total_median, 1),
            "comparison_margin_delta": round(adj.margin_median - base.margin_median, 1),
            "injury_note": bundle.injury_note,
            "def_tier_double_count_note": bundle.double_count_note,
            "home_off_drives_2026": profiles[g.home].n_off_drives if g.home in profiles else 0,
            "away_off_drives_2026": profiles[g.away].n_off_drives if g.away in profiles else 0,
            "adjustments": [
                {
                    "category": ln.category,
                    "label": ln.label,
                    "detail": ln.detail,
                    "delta_home_pts": ln.delta_home_pts,
                    "delta_away_pts": ln.delta_away_pts,
                    "delta_total_pts": ln.delta_total_pts,
                    "delta_margin_pts": ln.delta_margin_pts,
                    "delta_home_poss": ln.delta_home_poss,
                    "delta_away_poss": ln.delta_away_poss,
                    "delta_home_to": ln.delta_home_to,
                    "delta_away_to": ln.delta_away_to,
                }
                for ln in bundle.lines
            ],
        }
        if g.game_date:
            dt = g.game_date.replace(tzinfo=timezone.utc) if g.game_date.tzinfo is None else g.game_date
            row["kickoff_et"] = kickoff_et_label(dt)
        rows.append(row)

    team_medians = [r["base_home_median"] for r in rows] + [r["base_away_median"] for r in rows]
    adj_team = [r["adj_home_median"] for r in rows] + [r["adj_away_median"] for r in rows]
    totals = [r["base_total_median"] for r in rows]
    adj_totals = [r["adj_total_median"] for r in rows]
    sanity = {
        "season_2026_actual_team_pts_mean": actual.get("team_pts_mean"),
        "season_2026_actual_total_mean": actual.get("total_mean"),
        "slate_base_team_pts_mean": round(sum(team_medians) / max(len(team_medians), 1), 2),
        "slate_base_team_pts_min": round(min(team_medians), 2) if team_medians else None,
        "slate_base_team_pts_max": round(max(team_medians), 2) if team_medians else None,
        "slate_base_total_mean": round(sum(totals) / max(len(totals), 1), 2),
        "slate_adj_total_mean": round(sum(adj_totals) / max(len(adj_totals), 1), 2),
        "slate_base_total_min": round(min(totals), 2) if totals else None,
        "slate_base_total_max": round(max(totals), 2) if totals else None,
        "median_above_70_count_base": sum(1 for x in team_medians if x > 70),
        "median_above_70_count_adj": sum(1 for x in adj_team if x > 70),
        "n_sims_per_game": n_sims,
        "marginal_sims_per_tax": min(MARGINAL_SIMS, max(1500, n_sims // 5)),
        "n_games": len(rows),
        "espn_injury_teams_with_rows": len(injuries),
    }

    windows = default_projection_window()
    tag = file_tag
    if kickoff_et_date is not None and not tag:
        tag = f"tonight_{kickoff_et_date.strftime('%Y%m%d')}"
    stem = f"cfb_sim_slate_{season}_{tag}" if tag else f"cfb_sim_slate_{season}"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "cfb_drive_monte_carlo_2026_base_plus_adjusted",
        "season": season,
        "window": {k: [str(v[0]), str(v[1])] for k, v in windows.items()},
        "kickoff_et_date": str(kickoff_et_date) if kickoff_et_date else None,
        "slate_scope": f"kickoff_et={kickoff_et_date}" if kickoff_et_date else "full_window",
        "sanity": sanity,
        "games": rows,
    }

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    json_path = SHADOW_DIR / f"{stem}.json"
    csv_path = SHADOW_DIR / f"{stem}.csv"
    json_path.write_text(json.dumps(payload, indent=2) + "\n")
    if rows:
        flat_rows = []
        for r in rows:
            flat = {k: v for k, v in r.items() if k != "adjustments"}
            adjs = r.get("adjustments") or []
            flat["adjustments_json"] = json.dumps(adjs, separators=(",", ":"))
            flat["n_adjustments"] = len(adjs)
            flat_rows.append(flat)
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(flat_rows[0].keys()))
            w.writeheader()
            w.writerows(flat_rows)

    text_lines = _format_text_report(payload)
    text_path = SHADOW_DIR / f"{stem}.txt"
    text_path.write_text(text_lines + "\n")
    art = Path("/opt/cursor/artifacts")
    art.mkdir(parents=True, exist_ok=True)
    (art / f"{stem}.txt").write_text(text_lines + "\n")
    (art / f"{stem}.csv").write_text(csv_path.read_text() if csv_path.exists() else "")
    (art / f"{stem}.json").write_text(json_path.read_text())

    payload["paths"] = {
        "json": str(json_path.relative_to(DATA_DIR)),
        "csv": str(csv_path.relative_to(DATA_DIR)),
        "txt": str(text_path.relative_to(DATA_DIR)),
    }
    return payload


def _format_text_report(payload: dict[str, Any]) -> str:
    s = payload.get("sanity") or {}
    lines = [
        f"# CFB drive sim slate — season {payload.get('season')} (2026 PBP only)",
        f"Generated: {payload.get('generated_at')}",
        f"Slate scope: {payload.get('slate_scope') or 'full_window'}",
        f"Window: {payload.get('window')}",
        "",
        "## Sanity (BASE medians)",
        f"- 2026 actual mean team pts: {s.get('season_2026_actual_team_pts_mean')}",
        f"- 2026 actual mean total: {s.get('season_2026_actual_total_mean')}",
        f"- Slate BASE mean team pts: {s.get('slate_base_team_pts_mean')} "
        f"(min {s.get('slate_base_team_pts_min')}, max {s.get('slate_base_team_pts_max')})",
        f"- Slate BASE mean total: {s.get('slate_base_total_mean')} "
        f"(min {s.get('slate_base_total_min')}, max {s.get('slate_base_total_max')})",
        f"- Slate ADJ mean total: {s.get('slate_adj_total_mean')}",
        f"- Medians above 70 (base/adj): {s.get('median_above_70_count_base')} / {s.get('median_above_70_count_adj')}",
        f"- ESPN injury teams with rows: {s.get('espn_injury_teams_with_rows')}",
        "",
        "## Games (BASE then ADJUSTED; market line for comparison only)",
        "",
    ]
    for g in payload.get("games") or []:
        lines.append(
            f"{g.get('kickoff_et') or 'TBD'} | {g['away']} @ {g['home']}"
        )
        lines.append(
            f"  BASE  {g['base_away_median']}-{g['base_home_median']} total {g['base_total_median']} "
            f"margin {g['base_margin_median']:+.1f} | win% home {g['base_home_win_pct']} | "
            f"poss {g['base_away_poss']}/{g['base_home_poss']} | TO {g['base_away_to']}/{g['base_home_to']}"
        )
        lines.append(
            f"  ADJ   {g['adj_away_median']}-{g['adj_home_median']} total {g['adj_total_median']} "
            f"margin {g['adj_margin_median']:+.1f} | win% home {g['adj_home_win_pct']} | "
            f"poss {g['adj_away_poss']}/{g['adj_home_poss']} | TO {g['adj_away_to']}/{g['adj_home_to']}"
        )
        lines.append(
            f"  vs line spread {g.get('market_spread_home')} total {g.get('market_total')} | "
            f"BASE gaps tot {g.get('base_gap_total')} margin {g.get('base_gap_margin')} | "
            f"ADJ gaps tot {g.get('adj_gap_total')} margin {g.get('adj_gap_margin')}"
        )
        lines.append(
            f"  COMPARE adj-base: total {g.get('comparison_total_delta'):+.1f} margin {g.get('comparison_margin_delta'):+.1f}"
        )
        if g.get("injury_note"):
            lines.append(f"  Injuries: {g['injury_note']}")
        for adj in g.get("adjustments") or []:
            lines.append(
                f"    • {adj.get('label')}: {adj.get('detail')} | "
                f"Δ total {adj.get('delta_total_pts'):+.2f} margin {adj.get('delta_margin_pts'):+.2f} | "
                f"Δ poss H/A {adj.get('delta_home_poss'):+.2f}/{adj.get('delta_away_poss'):+.2f} | "
                f"Δ TO H/A {adj.get('delta_home_to'):+.2f}/{adj.get('delta_away_to'):+.2f}"
            )
        lines.append(f"  Note: {g.get('def_tier_double_count_note')}")
        lines.append("")
    return "\n".join(lines)
