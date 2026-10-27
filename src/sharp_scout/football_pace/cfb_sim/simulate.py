"""Monte Carlo possession / drive game simulation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sharp_scout.football_pace.cfb_sim.profiles import (
    HFA_POINTS,
    OUTCOMES,
    TeamProfile,
    adjusted_outcome_rates,
    get_profile,
)

N_SIMS_DEFAULT = 10_000
KICKOFF_YTG = 75.0


@dataclass
class SimSummary:
    home_median: float
    away_median: float
    total_median: float
    margin_median: float
    home_win_pct: float
    home_poss_mean: float
    away_poss_mean: float
    home_to_mean: float
    away_to_mean: float
    main_driver: str
    home_scores: np.ndarray
    away_scores: np.ndarray


def _sample_next_ytg(result: str, start_ytg: float, rng: np.random.Generator) -> float:
    if result == "td":
        return KICKOFF_YTG
    if result == "fg":
        return KICKOFF_YTG
    if result == "miss_fg":
        return float(rng.uniform(38, 55))
    if result == "punt":
        net = float(rng.normal(38, 8))
        return float(np.clip(100 - (start_ytg - net), 20, 95))
    if result in ("int", "fumble"):
        return float(rng.uniform(25, 65))
    if result == "downs":
        return float(rng.uniform(30, 70))
    return float(rng.uniform(35, 75))


def _simulate_one_game(
    home: TeamProfile,
    away: TeamProfile,
    rng: np.random.Generator,
) -> tuple[int, int, int, int, int, int]:
    home_pts = away_pts = 0
    home_poss = away_poss = 0
    home_to = away_to = 0
    n_home_d = max(8, int(rng.poisson(home.drives_per_game)))
    n_away_d = max(8, int(rng.poisson(away.drives_per_game)))
    total_drives = n_home_d + n_away_d

    offense_home = True
    ytg = KICKOFF_YTG
    for _ in range(total_drives):
        if offense_home:
            off, defn = home, away
            home_poss += 1
        else:
            off, defn = away, home
            away_poss += 1

        rates = adjusted_outcome_rates(off, defn)
        probs = np.array([rates[k] for k in OUTCOMES], dtype=float)
        probs /= probs.sum()
        result = OUTCOMES[int(rng.choice(len(OUTCOMES), p=probs))]

        if result == "td":
            if offense_home:
                home_pts += 7
            else:
                away_pts += 7
        elif result == "fg":
            if offense_home:
                home_pts += 3
            else:
                away_pts += 3
        elif result in ("int", "fumble"):
            if offense_home:
                home_to += 1
            else:
                away_to += 1

        ytg = _sample_next_ytg(result, ytg, rng)
        offense_home = not offense_home

    home_pts += int(round(HFA_POINTS / 2))
    away_pts -= int(round(HFA_POINTS / 2))
    return home_pts, away_pts, home_poss, away_poss, home_to, away_to


def simulate_matchup(
    home: str,
    away: str,
    profiles: dict[str, TeamProfile],
    *,
    home_profile: TeamProfile | None = None,
    away_profile: TeamProfile | None = None,
    n_sims: int = N_SIMS_DEFAULT,
    seed: int | None = None,
) -> SimSummary:
    hp = home_profile or get_profile(profiles, home)
    ap = away_profile or get_profile(profiles, away)
    rng = np.random.default_rng(seed)

    h_scores = np.empty(n_sims, dtype=np.int16)
    a_scores = np.empty(n_sims, dtype=np.int16)
    h_poss = np.empty(n_sims, dtype=np.float32)
    a_poss = np.empty(n_sims, dtype=np.float32)
    h_to = np.empty(n_sims, dtype=np.float32)
    a_to = np.empty(n_sims, dtype=np.float32)

    for i in range(n_sims):
        hs, as_, hp_, ap_, ht, at = _simulate_one_game(hp, ap, rng)
        h_scores[i] = hs
        a_scores[i] = as_
        h_poss[i] = hp_
        a_poss[i] = ap_
        h_to[i] = ht
        a_to[i] = at

    margin = h_scores.astype(float) - a_scores.astype(float)
    driver = _main_driver(hp, ap, profiles, home, away)

    return SimSummary(
        home_median=float(np.median(h_scores)),
        away_median=float(np.median(a_scores)),
        total_median=float(np.median(h_scores + a_scores)),
        margin_median=float(np.median(margin)),
        home_win_pct=round(float(np.mean(h_scores > a_scores)) * 100, 2),
        home_poss_mean=round(float(h_poss.mean()), 2),
        away_poss_mean=round(float(a_poss.mean()), 2),
        home_to_mean=round(float(h_to.mean()), 2),
        away_to_mean=round(float(a_to.mean()), 2),
        main_driver=driver,
        home_scores=h_scores,
        away_scores=a_scores,
    )


def _main_driver(hp: TeamProfile, ap: TeamProfile, profiles, home: str, away: str) -> str:
    """Heuristic: largest deviation from league-neutral opponent."""
    league = get_profile(profiles, "__league__") if "__league__" in profiles else hp
    pace_delta = abs(hp.drives_per_game - league.drives_per_game) + abs(ap.drives_per_game - league.drives_per_game)
    eff_delta = abs(hp.outcome_rates.get("td", 0.22) - 0.22) + abs(ap.outcome_rates.get("td", 0.22) - 0.22)
    to_delta = abs(hp.int_rate + hp.fumble_rate - 0.09) + abs(ap.int_rate + ap.fumble_rate - 0.09)
    scores = {"pace": pace_delta, "efficiency": eff_delta, "turnovers": to_delta}
    return max(scores, key=scores.get)
