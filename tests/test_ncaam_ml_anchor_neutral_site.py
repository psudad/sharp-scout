"""Nov 2 2026 NCAAM fixes: Pinnacle ML fair prob and neutral-site home/away matching."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from sharp_scout.data.odds_api import OddsClient
from sharp_scout.ncaam import candidates as cand
from sharp_scout.ncaam import sharp3
from sharp_scout.ncaam.rules import RULES, anchor_k_spread, candidate_ev, ev_qualifies
from sharp_scout.ncaam.settle import settle_ncaam_ledger
from sharp_scout.ncaam.slate import build_slate, orient_to_odds_event
from sharp_scout.phase3.market import anchor_probability
from sharp_scout.site.ncaam_page import ncaam_record
from sharp_scout.sports import NCAAM

NOW = datetime(2026, 11, 2, 22, 38, tzinfo=timezone.utc)


def _pin_event(h2h_home: float | None, h2h_away: float | None, *, soft_home_ml: float = 192.0) -> dict:
    """Charlotte @ Indiana St., Nov 2 2026: Pinnacle +187 / -223, soft book Indiana St. +192."""
    pin_h2h = []
    if h2h_home is not None:
        pin_h2h.append({"side": "home", "price": h2h_home})
    if h2h_away is not None:
        pin_h2h.append({"side": "away", "price": h2h_away})
    return {
        "event_id": "51227b1c18baf285bc96ead01820bb34",
        "home_team": "Indiana St.",
        "away_team": "Charlotte",
        "bookmakers": {
            "pinnacle": {
                "last_update": NOW.isoformat(),
                "markets": {
                    "spreads": [
                        {"side": "home", "price": -110, "point": 4.5},
                        {"side": "away", "price": -110, "point": -4.5},
                    ],
                    "h2h": pin_h2h,
                },
            },
            "betonlineag": {
                "last_update": NOW.isoformat(),
                "markets": {"h2h": [{"side": "home", "price": soft_home_ml}, {"side": "away", "price": -240}]},
            },
        },
    }


GAME = {
    "espn_id": "401000001",
    "home_team": "Indiana St.",
    "away_team": "Charlotte",
    "commence_time": NOW + timedelta(minutes=80),
    "neutral_site": False,
}


def test_pinnacle_ml_fair_uses_real_devigged_prices():
    ev = _pin_event(187, -223)
    p_home = cand._pinnacle_h2h_fair(ev, "home")
    p_away = cand._pinnacle_h2h_fair(ev, "away")
    assert p_home == pytest.approx(0.3354, abs=1e-3)  # ~34%, not ~50%
    assert p_home + p_away == pytest.approx(1.0)


@pytest.mark.parametrize(
    "outs",
    [
        [],  # no Pinnacle h2h
        [{"side": "home", "price": 187}],  # one side missing
        [{"side": "home", "price": 187}, {"side": "home", "price": -223}],  # both claim home
        [{"side": "Some Other Team", "price": 187}, {"side": "away", "price": -223}],  # unmatched name
    ],
)
def test_pinnacle_ml_fair_none_when_missing_or_unmatched(outs):
    ev = _pin_event(None, None)
    ev["bookmakers"]["pinnacle"]["markets"]["h2h"] = outs
    assert cand._pinnacle_h2h_fair(ev, "home") is None
    assert cand._pinnacle_h2h_fair(ev, "away") is None


def test_indiana_st_plus192_has_no_edge_with_model_23_7():
    p_fair = cand._pinnacle_h2h_fair(_pin_event(187, -223), "home")
    p_true = anchor_probability(0.2368, p_fair, anchor_k_spread(NOW), RULES.anchor_tilt_cap)
    ev = candidate_ev(p_true, 192.0, 0.0)
    assert p_true < p_fair
    assert not ev_qualifies(ev)


def _patch_model(monkeypatch, p_model_home: float):
    class _Proj:
        margin_model = -7.5

    monkeypatch.setattr(cand, "_pinnacle_spread_age_ok", lambda e, n: True)
    monkeypatch.setattr(cand, "ratings_for_team", lambda t, r: {"x": 1})
    monkeypatch.setattr(cand, "project_game", lambda **k: _Proj())
    monkeypatch.setattr(cand, "simulate_margin", lambda p: None)
    monkeypatch.setattr(cand, "model_gap_qualifies", lambda m, l: True)
    monkeypatch.setattr(cand, "p_cover_side", lambda m, s, l: (0.0, 0.0))  # no spread candidates
    monkeypatch.setattr(
        cand, "p_ml_side", lambda m, s: ((p_model_home if s == "home" else 1 - p_model_home), 0.0)
    )


def test_evaluate_game_no_ml_play_for_indiana_st_case(monkeypatch):
    _patch_model(monkeypatch, 0.2368)
    cands = cand.evaluate_game(GAME, _pin_event(187, -223), {}, now=NOW)
    assert not [c for c in cands if c["market"] == "h2h" and c["side"] == "home"]


def test_evaluate_game_no_ml_play_without_pinnacle_ml(monkeypatch):
    _patch_model(monkeypatch, 0.60)  # even a big model edge must not use a 50% default
    cands = cand.evaluate_game(GAME, _pin_event(None, None), {}, now=NOW)
    assert not [c for c in cands if c["market"] == "h2h"]


def test_evaluate_game_ml_fair_recorded_is_pinnacle(monkeypatch):
    _patch_model(monkeypatch, 0.60)
    cands = cand.evaluate_game(GAME, _pin_event(187, -223), {}, now=NOW)
    for c in cands:
        if c["market"] == "h2h":
            assert c["p_fair"] == pytest.approx(cand._pinnacle_h2h_fair(_pin_event(187, -223), c["side"]))
            assert c["selection"] == GAME[f"{c['side']}_team"]


# ---- Neutral-site home/away: Purdue vs Gonzaga, Nov 2 2026 (ESPN 401921704) ----

RAW_ODDS_EVENT = {
    # The Odds API listed Gonzaga as home; DraftKings Gonzaga -5.5 / Purdue +5.5 (-115).
    "id": "104fd9502f231c9207ee53d73289d028",
    "sport_key": "basketball_ncaab",
    "commence_time": "2026-11-03T00:30:00Z",
    "home_team": "Gonzaga Bulldogs",
    "away_team": "Purdue Boilermakers",
    "bookmakers": [
        {
            "key": "draftkings",
            "title": "DraftKings",
            "last_update": "2026-11-02T23:08:00Z",
            "markets": [
                {
                    "key": "spreads",
                    "outcomes": [
                        {"name": "Purdue Boilermakers", "price": -115, "point": 5.5},
                        {"name": "Gonzaga Bulldogs", "price": -105, "point": -5.5},
                    ],
                },
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Gonzaga Bulldogs", "price": -250},
                        {"name": "Purdue Boilermakers", "price": 205},
                    ],
                },
            ],
        }
    ],
}


def _espn_row(home: str, away: str, *, neutral: bool = True) -> dict:
    return {
        "espn_id": "401921704",
        "home_location": home,
        "away_location": away,
        "home_team": home,
        "away_team": away,
        "home_espn_team_id": "2509" if home == "Purdue" else "2250",
        "away_espn_team_id": "2250" if home == "Purdue" else "2509",
        "commence_time": datetime(2026, 11, 3, 0, 30, tzinfo=timezone.utc),
        "neutral_site": neutral,
    }


@pytest.fixture
def odds_event():
    return OddsClient(api_key="test", sport=NCAAM)._normalize_event(json.loads(json.dumps(RAW_ODDS_EVENT)))


@pytest.mark.parametrize("espn_home,espn_away", [("Purdue", "Gonzaga"), ("Gonzaga", "Purdue")])
def test_slate_uses_odds_api_frame_whatever_espn_says(odds_event, espn_home, espn_away):
    slate = build_slate(
        et_day=datetime(2026, 11, 2).date(),
        odds_events=[odds_event],
        espn_rows=[_espn_row(espn_home, espn_away)],
    )
    assert len(slate) == 1
    g = slate[0]
    assert (g["home_team"], g["away_team"]) == ("Gonzaga", "Purdue")
    assert g["odds_event_id"] == odds_event["event_id"]
    assert g["espn_swapped"] is (espn_home == "Purdue")
    assert g["home_espn_team_id"] == "2250"  # Gonzaga's ESPN id moves with the team

    # The away-side DraftKings quote is Purdue's, and the selection names Purdue.
    offer = sharp3._book_offer(odds_event, "spreads", "away")
    assert offer == {"book": "draftkings", "price": -115.0, "line": 5.5}
    assert g["away_team"] == "Purdue"


def test_non_neutral_home_disagreement_gets_no_odds(odds_event):
    row = _espn_row("Purdue", "Gonzaga", neutral=False)
    assert orient_to_odds_event(row, odds_event) is None
    slate = build_slate(et_day=datetime(2026, 11, 2).date(), odds_events=[odds_event], espn_rows=[row])
    assert "odds_event_id" not in slate[0]


@pytest.mark.parametrize(
    "espn_home,espn_away,hs,aw",
    [
        ("Gonzaga", "Purdue", 72, 70),  # ESPN agrees with the ledger frame
        ("Purdue", "Gonzaga", 70, 72),  # ESPN lists the teams the other way round
    ],
)
def test_settle_grades_by_team_name(tmp_path, espn_home, espn_away, hs, aw):
    path = tmp_path / "sharp3_ledger.json"
    path.write_text(
        json.dumps(
            {
                "plays": [
                    {
                        "espn_id": "401921704",
                        "event_id": "104fd9502f231c9207ee53d73289d028",
                        "market": "spreads",
                        "side": "away",
                        "selection": "Purdue",
                        "home_team": "Gonzaga",
                        "away_team": "Purdue",
                        "line": 5.5,
                        "price": -115,
                        "units": 2.0,
                        "status": "pending",
                        "locked_at": "2026-11-02T23:08:57+00:00",
                    }
                ]
            }
        )
    )
    scores = [
        {"espn_id": "401921704", "home_team": espn_home, "away_team": espn_away, "home_score": hs, "away_score": aw}
    ]
    led = settle_ncaam_ledger(path=path, scores=scores)
    play = led["plays"][0]
    # Gonzaga 72, Purdue 70: Purdue +5.5 covers either way.
    assert play["status"] == "win"
    assert (play["home_score"], play["away_score"]) == (72, 70)


def test_record_ignores_no_play_rows_and_voids():
    ledger = {
        "starting_units": 100.0,
        "plays": [
            {"espn_id": "1", "status": "no_play", "market": "spreads"},
            {"espn_id": "2", "status": "missed", "side": None},
            {"espn_id": "3", "status": "void", "side": "home", "units": 0.0, "pnl_units": 0.0, "clv_points": 2.0},
            {"espn_id": "4", "status": "pending", "side": "home", "units": 1.0},
            {"espn_id": "5", "status": "win", "side": "away", "units": 1.0, "pnl_units": 0.91},
        ],
    }
    rec = ncaam_record(ledger)
    assert rec["pending"] == 1
    assert rec["void"] == 1
    assert rec["record"] == "1-0"
    assert rec["pnl_units"] == pytest.approx(0.91)
    assert rec["n_plays"] == 3
    assert rec["n_no_play"] == 2
    assert rec["clv"]["n_plays_with_clv"] == 0


def test_manual_overrides_void_survives_regrading(tmp_path):
    from sharp_scout.ncaam.settle import apply_manual_overrides

    ov = tmp_path / "manual_overrides.json"
    ov.write_text(
        json.dumps(
            {
                "overrides": [
                    {"ledger": "ncaam_ledger.json", "id": "a", "action": "void", "reason": "false edge",
                     "approved_at": "2026-11-03T00:44:00+00:00"},
                    {"ledger": "sharp3_ledger.json", "id": "b", "action": "void", "reason": "flip",
                     "approved_at": "2026-11-03T01:01:00+00:00"},
                ]
            }
        )
    )
    # Row already graded by an older runner: the void still wins and zeroes the P&L.
    led = {"plays": [{"id": "a", "status": "loss", "side": "home", "units": 1.0, "pnl_units": -1.0},
                     {"id": "b", "status": "pending", "side": "away", "units": 2.0}]}
    assert apply_manual_overrides(led, ledger_name="ncaam_ledger.json", path=ov)
    a = led["plays"][0]
    assert (a["status"], a["units"], a["pnl_units"]) == ("void", 0.0, 0.0)
    assert led["plays"][1]["status"] == "pending"  # other ledger's override not applied here
    assert not apply_manual_overrides(led, ledger_name="ncaam_ledger.json", path=ov)  # idempotent
    assert apply_manual_overrides(led, ledger_name="sharp3_ledger.json", path=ov)
    assert led["plays"][1]["status"] == "void"
    assert ncaam_record(led)["record"] == "0-0"


def test_sharp3_gonzaga_purdue_void_excluded_and_never_regraded(tmp_path, monkeypatch):
    """Sharp 3 Purdue vs Gonzaga (ESPN 401921704) is void at 0u; settle must never grade it."""
    from sharp_scout.ncaam import settle as settle_mod

    reason = ("Neutral-site home/away flip: signal pointed at Gonzaga but Purdue's price was "
              "locked; voided per Jason Nov 2.")
    ov = tmp_path / "manual_overrides.json"
    ov.write_text(json.dumps({"overrides": [
        {"ledger": "sharp3_ledger.json", "id": "g", "action": "void", "reason": reason,
         "approved_at": "2026-11-03T01:01:00+00:00"}]}))
    monkeypatch.setattr(settle_mod, "MANUAL_OVERRIDES_PATH", ov)
    monkeypatch.setattr(settle_mod, "finalize_closing_lines", lambda *a, **k: 0)
    ledger_path = tmp_path / "sharp3_ledger.json"
    # As the old runner would push it: still pending at 2u, labeled with the flipped frame.
    ledger_path.write_text(json.dumps({"plays": [
        {"id": "g", "espn_id": "401921704", "market": "spreads", "side": "away", "line": 5.5,
         "price": -115.0, "units": 2.0, "status": "pending", "selection": "Gonzaga",
         "home_team": "Purdue", "away_team": "Gonzaga"},
        {"id": "w", "espn_id": "9", "market": "spreads", "side": "home", "line": -1.5,
         "price": -110.0, "units": 1.0, "status": "pending", "home_team": "A", "away_team": "B"},
    ]}))
    scores = [
        {"espn_id": "401921704", "home_team": "Gonzaga", "away_team": "Purdue",
         "home_score": 70, "away_score": 80},
        {"espn_id": "9", "home_team": "A", "away_team": "B", "home_score": 80, "away_score": 70},
    ]
    for _ in range(2):  # second pass: still void, never regraded
        led = settle_mod.settle_ncaam_ledger(path=ledger_path, scores=scores)
        g = next(p for p in led["plays"] if p["id"] == "g")
        assert (g["status"], g["units"], g["pnl_units"]) == ("void", 0.0, 0.0)
        assert g["void_reason"] == reason
        assert "settled_at" not in g and "home_score" not in g
    # A stale copy that an old runner had already graded is forced back to void as well.
    stale = json.loads(ledger_path.read_text())
    stale["plays"][0].update(status="win", units=2.0, pnl_units=1.739, settled_at="x")
    ledger_path.write_text(json.dumps(stale))
    led = settle_mod.settle_ncaam_ledger(path=ledger_path, scores=scores)
    g = led["plays"][0]
    assert (g["status"], g["units"], g["pnl_units"]) == ("void", 0.0, 0.0)
    rec = ncaam_record(led)
    assert rec["record"] == "1-0"  # only the other play
    assert rec["void"] == 1 and rec["pending"] == 0
    assert rec["pnl_units"] == pytest.approx(0.91, abs=0.005)  # +0.909u at -110


def test_repo_sharp3_gonzaga_purdue_row_is_void():
    from sharp_scout.config import DATA_DIR

    gid = "1809664a-4a7c-4f6a-9c0e-50ea1acbb60c"
    ov = json.loads((DATA_DIR / "ncaam" / "manual_overrides.json").read_text())["overrides"]
    o = next(o for o in ov if o["id"] == gid)
    assert (o["ledger"], o["action"]) == ("sharp3_ledger.json", "void")
    # Other owner-approved "set" corrections may exist (e.g. team-label fixes);
    # this row must stay a void and must not be converted to set.
    assert o.get("action") == "void"
    row = next(p for p in json.loads((DATA_DIR / "ncaam" / "sharp3_ledger.json").read_text())["plays"]
               if p["id"] == gid)
    assert (row["status"], row["units"], row["pnl_units"]) == ("void", 0.0, 0.0)
    assert row["void_reason"] == o["reason"]


# --- Nov 3 2026: extreme-price / implied-total guard (same rule as NBA) ---


@pytest.mark.parametrize(
    "home,away",
    [
        (-10000, -10000),  # Betfair-style placeholder
        (-2000, 1200),  # at the extreme-price limit
        (2000, -5000),
        (-110, 300),  # implied total < 1.00 (stale side)
        (-200, -200),  # implied total > 1.10
        (50, -110),  # not a valid American price
    ],
)
def test_pinnacle_ml_guard_rejects_bad_prices(home, away):
    ev = _pin_event(home, away)
    assert cand._pinnacle_h2h_fair(ev, "home") is None
    assert cand._pinnacle_h2h_fair(ev, "away") is None


def test_pinnacle_ml_guard_keeps_normal_prices():
    for home, away in [(187, -223), (-1900, 1100), (-105, -115)]:
        p = cand._pinnacle_h2h_fair(_pin_event(home, away), "home")
        assert p is not None and 0.0 < p < 1.0


def test_placeholder_pinnacle_ml_produces_no_ml_candidate():
    ev = _pin_event(-10000, -10000)
    assert cand._pinnacle_h2h_fair(ev, "home") is None
