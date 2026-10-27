"""Itemized matchup taxes on top of base 2026 profiles (ADJUSTED sim)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np

from sharp_scout.football_pace.cfb_sim.profiles import LEAGUE, TeamProfile, get_profile
from sharp_scout.football_pace.cfb_sim.simulate import SimSummary, simulate_matchup

ELITE_RANK_CUTOFF = 25
MARGINAL_SIMS = 2_000

# Base sim already scales TD/TO by empirical def_td_allow / def_to_forced (see adjusted_outcome_rates).
# Elite tier applies only an incremental EPA-rank tail (top/bottom 25), not a second full opponent pass.
ELITE_TD_TAIL_MAX = 0.055
WEAK_TD_TAIL_MAX = 0.045

SEASON_LONG_MARKERS = (
    "season",
    "out for the season",
    "out indefinitely",
    "medical",
    "redshirt",
    "will miss the season",
    "expected to miss the season",
)


@dataclass
class AdjustmentLine:
    category: str
    label: str
    detail: str
    delta_home_pts: float = 0.0
    delta_away_pts: float = 0.0
    delta_total_pts: float = 0.0
    delta_margin_pts: float = 0.0
    delta_home_poss: float = 0.0
    delta_away_poss: float = 0.0
    delta_home_to: float = 0.0
    delta_away_to: float = 0.0


@dataclass
class AdjustedBundle:
    home: TeamProfile
    away: TeamProfile
    lines: list[AdjustmentLine] = field(default_factory=list)
    injury_note: str = ""
    double_count_note: str = (
        "Base sim already opponent-shades TD and TO via def_td_allow / def_to_forced; "
        "elite/weak defense tax adds only a rank-based tail (top/bottom 25 EPA/play allowed) "
        "so full defensive quality is not applied twice."
    )


def _clone(p: TeamProfile) -> TeamProfile:
    return copy.deepcopy(p)


def _pace_grind_index(p: TeamProfile, league_spp: float, league_rush: float) -> float:
    rush_heavy = (1.0 - p.pass_play_share) - league_rush
    tempo_slow = (p.sec_per_play / max(league_spp, 4.0)) - 1.0
    return float(0.55 * tempo_slow + 0.45 * rush_heavy)


def pace_possession_multiplier(home: TeamProfile, away: TeamProfile, league: dict[str, float]) -> tuple[float, str]:
    """Interaction of both teams' tempo + run mix (not a simple average)."""
    spp = league.get("sec_per_play", 5.5)
    rush = league.get("rush_share", 0.45)
    gh = _pace_grind_index(home, spp, rush)
    ga = _pace_grind_index(away, spp, rush)
    # Two grind-heavy teams shrink shared possession pool; two up-tempo teams expand it.
    interaction = gh * ga
    mult = float(np.clip(1.0 - 0.22 * interaction - 0.08 * (gh + ga), 0.82, 1.18))
    detail = (
        f"home grind={gh:+.2f} away grind={ga:+.2f} interaction={interaction:+.3f} → "
        f"possession multiplier {mult:.3f} on both teams' drive rates"
    )
    return mult, detail


def _apply_pace_to_pair(home: TeamProfile, away: TeamProfile, mult: float) -> None:
    for p in (home, away):
        p.drives_per_game = float(np.clip(p.drives_per_game * mult, 7.0, 17.0))


def _elite_def_td_factor(defn: TeamProfile, n_teams: int) -> tuple[float, str]:
    rank = defn.def_epa_rank
    if rank is None or n_teams < 30:
        return 1.0, "def EPA rank unavailable — no elite tail"
    if rank <= ELITE_RANK_CUTOFF:
        tail = ELITE_TD_TAIL_MAX * (ELITE_RANK_CUTOFF - rank + 1) / ELITE_RANK_CUTOFF
        return 1.0 - tail, f"elite defense rank {rank}/{n_teams} → TD rate ×{1.0 - tail:.3f}"
    if rank > n_teams - ELITE_RANK_CUTOFF:
        weak_rank = n_teams - rank + 1
        tail = WEAK_TD_TAIL_MAX * weak_rank / ELITE_RANK_CUTOFF
        return 1.0 + tail, f"weak defense rank {rank}/{n_teams} → TD rate ×{1.0 + tail:.3f}"
    return 1.0, f"middle-tier defense rank {rank}/{n_teams} — no elite tail"


def _scale_offense_td(off: TeamProfile, factor: float) -> None:
    if abs(factor - 1.0) < 1e-6:
        return
    rates = dict(off.outcome_rates)
    rates["td"] = max(0.05, rates.get("td", LEAGUE["td"]) * factor)
    s = sum(rates.values())
    off.outcome_rates = {k: v / s for k, v in rates.items()}


def _injury_is_season_long(status: str, detail: str) -> bool:
    blob = f"{status} {detail}".lower()
    return any(m in blob for m in SEASON_LONG_MARKERS)


def _injury_tax_for_team(team: TeamProfile, rows: list[dict]) -> tuple[float, str]:
    """Return composite offensive tax (1.0 = none) and human summary."""
    active = [
        r
        for r in rows
        if str(r.get("status", "")).lower() in ("out", "doubtful", "day-to-day")
        and not _injury_is_season_long(str(r.get("status", "")), str(r.get("detail", "")))
    ]
    if not active:
        return 1.0, ""

    tax = 1.0
    parts: list[str] = []
    for r in active:
        pos = str(r.get("position", "")).upper()
        name = r.get("player", "?")
        st = r.get("status", "")
        if pos == "QB":
            tax *= 0.86
            parts.append(f"QB {name} ({st})")
        elif pos in ("RB", "WR", "TE"):
            tax *= 0.97
            parts.append(f"{pos} {name} ({st})")
        elif pos in ("OT", "OG", "C", "OL", "G", "T"):
            tax *= 0.98
            parts.append(f"OL {name} ({st})")
        elif pos in ("DE", "DT", "LB", "CB", "S", "DB"):
            tax *= 0.995
            parts.append(f"DEF {name} ({st})")
        else:
            parts.append(f"{pos or '?'} {name} ({st})")

    tax = max(0.72, tax)
    return tax, "; ".join(parts[:8]) + ("…" if len(parts) > 8 else "")


def _turnover_interaction(off: TeamProfile, defn: TeamProfile, league_to: float, league_havoc: float) -> tuple[float, str]:
    off_to = off.int_rate + off.fumble_rate
    if off_to < league_to + 0.015 or defn.havoc_rate < league_havoc + 0.012:
        return 1.0, "no turnover environment bump"
    bump = 1.0 + min(0.22, 0.8 * (off_to - league_to) * (defn.havoc_rate - league_havoc) * 120.0)
    return bump, (
        f"TO-prone offense ({off_to:.3f}) vs havoc D ({defn.havoc_rate:.3f}) → "
        f"INT/fumble rate ×{bump:.3f}"
    )


def _apply_to_bump(off: TeamProfile, mult: float) -> None:
    if abs(mult - 1.0) < 1e-6:
        return
    off.int_rate = min(0.14, off.int_rate * mult)
    off.fumble_rate = min(0.12, off.fumble_rate * mult)
    rates = dict(off.outcome_rates)
    for k in ("int", "fumble"):
        rates[k] = min(0.15, rates.get(k, LEAGUE[k]) * mult)
    s = sum(rates.values())
    off.outcome_rates = {k: v / s for k, v in rates.items()}


def league_context(profiles: dict[str, TeamProfile]) -> dict[str, float]:
    if not profiles:
        return {"sec_per_play": 5.5, "rush_share": 0.45, "to_rate": 0.09, "havoc": 0.08, "n_teams": 0}
    vals = list(profiles.values())
    return {
        "sec_per_play": float(np.mean([p.sec_per_play for p in vals])),
        "rush_share": float(np.mean([1.0 - p.pass_play_share for p in vals])),
        "to_rate": float(np.mean([p.int_rate + p.fumble_rate for p in vals])),
        "havoc": float(np.mean([p.havoc_rate for p in vals])),
        "n_teams": len(vals),
    }


def build_adjusted_profiles(
    home: str,
    away: str,
    profiles: dict[str, TeamProfile],
    injuries_by_team: dict[str, list[dict]],
) -> AdjustedBundle:
    league = league_context(profiles)
    n_teams = int(league["n_teams"])
    hp = _clone(get_profile(profiles, home))
    ap = _clone(get_profile(profiles, away))
    lines: list[AdjustmentLine] = []

    mult, pace_detail = pace_possession_multiplier(hp, ap, league)
    if abs(mult - 1.0) > 0.005:
        _apply_pace_to_pair(hp, ap, mult)
        lines.append(
            AdjustmentLine(
                category="pace_style",
                label="Style / pace interaction",
                detail=pace_detail,
            )
        )

    for off, defn, side in ((hp, ap, "home"), (ap, hp, "away")):
        fac, detail = _elite_def_td_factor(defn, n_teams)
        if abs(fac - 1.0) > 1e-4:
            _scale_offense_td(off, fac)
            lines.append(
                AdjustmentLine(
                    category="def_tier",
                    label=f"Defensive tier ({side} offense)",
                    detail=detail,
                )
            )

    injury_bits: list[str] = []
    thin = True
    for team, prof, side in ((home, hp, "home"), (away, ap, "away")):
        rows = injuries_by_team.get(team) or []
        if rows:
            thin = False
        tax, summary = _injury_tax_for_team(prof, rows)
        if summary:
            _scale_offense_td(prof, tax)
            injury_bits.append(f"{side}: {summary}")
            lines.append(
                AdjustmentLine(
                    category="injury",
                    label=f"Key absences ({side})",
                    detail=summary,
                )
            )
    injury_note = ""
    if thin:
        injury_note = "ESPN CFB injury feed thin or empty for this matchup — no injury tax applied."
    elif injury_bits:
        injury_note = " | ".join(injury_bits)

    for off, defn, side in ((hp, ap, "home"), (ap, hp, "away")):
        bump, detail = _turnover_interaction(off, defn, league["to_rate"], league["havoc"])
        if abs(bump - 1.0) > 0.01:
            _apply_to_bump(off, bump)
            lines.append(
                AdjustmentLine(
                    category="turnover_env",
                    label=f"Turnover environment ({side} offense)",
                    detail=detail,
                )
            )

    return AdjustedBundle(home=hp, away=ap, lines=lines, injury_note=injury_note)


def _summary_deltas(base: SimSummary, other: SimSummary) -> AdjustmentLine:
    return AdjustmentLine(
        category="_delta",
        label="",
        detail="",
        delta_home_pts=round(other.home_median - base.home_median, 2),
        delta_away_pts=round(other.away_median - base.away_median, 2),
        delta_total_pts=round(other.total_median - base.total_median, 2),
        delta_margin_pts=round(other.margin_median - base.margin_median, 2),
        delta_home_poss=round(other.home_poss_mean - base.home_poss_mean, 2),
        delta_away_poss=round(other.away_poss_mean - base.away_poss_mean, 2),
        delta_home_to=round(other.home_to_mean - base.home_to_mean, 2),
        delta_away_to=round(other.away_to_mean - base.away_to_mean, 2),
    )


def _apply_single_category(
    home: str,
    away: str,
    profiles: dict[str, TeamProfile],
    injuries_by_team: dict[str, list[dict]],
    category: str,
) -> tuple[TeamProfile, TeamProfile]:
    """Apply only one tax category on top of base profiles."""
    league = league_context(profiles)
    n_teams = int(league["n_teams"])
    hp = _clone(get_profile(profiles, home))
    ap = _clone(get_profile(profiles, away))

    if category == "pace_style":
        mult, _ = pace_possession_multiplier(hp, ap, league)
        _apply_pace_to_pair(hp, ap, mult)
    elif category == "def_tier":
        for off, defn in ((hp, ap), (ap, hp)):
            fac, _ = _elite_def_td_factor(defn, n_teams)
            _scale_offense_td(off, fac)
    elif category == "injury":
        for team, prof in ((home, hp), (away, ap)):
            tax, _ = _injury_tax_for_team(prof, injuries_by_team.get(team) or [])
            _scale_offense_td(prof, tax)
    elif category == "turnover_env":
        for off, defn in ((hp, ap), (ap, hp)):
            bump, _ = _turnover_interaction(off, defn, league["to_rate"], league["havoc"])
            _apply_to_bump(off, bump)
    return hp, ap


def measure_all_impacts(
    home: str,
    away: str,
    profiles: dict[str, TeamProfile],
    injuries_by_team: dict[str, list[dict]],
    bundle: AdjustedBundle,
    *,
    seed: int,
    n_sims: int = MARGINAL_SIMS,
) -> list[AdjustmentLine]:
    base = simulate_matchup(home, away, profiles, n_sims=n_sims, seed=seed)
    measured: list[AdjustmentLine] = []
    for line in bundle.lines:
        hp, ap = _apply_single_category(home, away, profiles, injuries_by_team, line.category)
        sim = simulate_matchup(home, away, profiles, home_profile=hp, away_profile=ap, n_sims=n_sims, seed=seed)
        d = _summary_deltas(base, sim)
        line.delta_home_pts = d.delta_home_pts
        line.delta_away_pts = d.delta_away_pts
        line.delta_total_pts = d.delta_total_pts
        line.delta_margin_pts = d.delta_margin_pts
        line.delta_home_poss = d.delta_home_poss
        line.delta_away_poss = d.delta_away_poss
        line.delta_home_to = d.delta_home_to
        line.delta_away_to = d.delta_away_to
        measured.append(line)
    return measured
