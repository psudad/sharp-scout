"""Sharp 3 Monte Carlo projection (replaces fabricated sim_rec)."""

from __future__ import annotations

import importlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sharp_scout.ncaam import sharp3
from sharp_scout.ncaam.ratings import load_ratings, ratings_as_of_from_path, ratings_provenance_for_path
from sharp_scout.ncaam.rules import RULES
from sharp_scout.ncaam.sharp3_sim import (
    DISPLAY_MAX_RATING_AGE_DAYS,
    format_sim_rec,
    is_legacy_fabricated_sim_rec,
    is_valid_sim_projection,
    lab_sim_display_text,
    monte_carlo_projection,
    validate_ratings_for_sharp3_display,
)


FIXTURE_RATINGS = load_ratings(Path("tests/fixtures/ncaam/torvik_sample.csv"))
FIXTURE_PROVENANCE = json.loads(
    (Path(__file__).parent / "fixtures" / "ncaam" / "torvik_sample.provenance.json").read_text()
)
FIXTURE_NOW = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
EVAL_NOW = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)


def _mc(game, **kw):
    kw.setdefault("ratings_provenance", FIXTURE_PROVENANCE)
    kw.setdefault("now", FIXTURE_NOW)
    return monte_carlo_projection(game, **kw)


def test_sharp3_module_has_no_random_sim_record():
    src = inspect.getsource(importlib.import_module("sharp_scout.ncaam.sharp3"))
    assert "sim_record" not in src
    assert "random.Random" not in src


def test_monte_carlo_unavailable_without_ratings():
    game = {"espn_id": "1", "home_team": "Duke", "away_team": "North Carolina"}
    out = monte_carlo_projection(
        game, side="home", market="spreads", line=-4.5, ratings=None, ratings_provenance=None
    )
    assert out["status"] == "unavailable"
    assert out["reason"] == "ratings_provenance_missing"
    assert format_sim_rec(out) is None


def test_monte_carlo_unavailable_missing_team_ratings():
    game = {"espn_id": "2", "home_team": "Duke", "away_team": "Not A Real Team XYZ"}
    out = _mc(
        game, side="home", market="spreads", line=-4.5, ratings=FIXTURE_RATINGS
    )
    assert out["status"] == "unavailable"
    assert out["reason"] == "missing_team_ratings"


def test_ratings_freshness_policy_fresh_stale_missing(tmp_path):
    assert DISPLAY_MAX_RATING_AGE_DAYS == 1
    fresh = tmp_path / "ratings_20261107.csv"
    fresh.write_text("x", encoding="utf-8")
    stale = tmp_path / "ratings_20261105.csv"
    stale.write_text("x", encoding="utf-8")
    latest = tmp_path / "ratings_latest.csv"
    latest.write_text("x", encoding="utf-8")
    assert ratings_as_of_from_path(fresh) == EVAL_NOW.date()
    ok, _ = validate_ratings_for_sharp3_display(ratings_provenance_for_path(fresh), now=EVAL_NOW)
    assert ok
    ok, reason = validate_ratings_for_sharp3_display(ratings_provenance_for_path(stale), now=EVAL_NOW)
    assert not ok and reason == "ratings_stale_for_display"
    ok, reason = validate_ratings_for_sharp3_display(ratings_provenance_for_path(latest), now=EVAL_NOW)
    assert not ok and reason == "ratings_as_of_missing"
    prov = ratings_provenance_for_path(fresh)
    assert prov["fetched_at_utc"] is not None
    assert prov["ratings_as_of"] == "2026-11-07"
    assert prov["ratings_as_of_derivation"] == "filename ratings_YYYYMMDD.csv"


def test_projection_includes_reproducibility_seed():
    game = {"espn_id": "401", "home_team": "Duke", "away_team": "North Carolina"}
    out = _mc(
        game, side="home", market="spreads", line=-4.5, ratings=FIXTURE_RATINGS, n=100
    )
    rep = out["reproducibility"]
    assert "sharp3-sim|401|home|spreads|-4.5" == rep["seed_inputs"]
    assert isinstance(rep["seed"], int)


def test_monte_carlo_deterministic_and_counts_sum_to_n():
    game = {"espn_id": "401", "home_team": "Duke", "away_team": "North Carolina", "neutral_site": False}
    n = 2000
    a = _mc(game, side="home", market="spreads", line=-4.5, ratings=FIXTURE_RATINGS, n=n)
    b = _mc(game, side="home", market="spreads", line=-4.5, ratings=FIXTURE_RATINGS, n=n)
    assert a == b
    assert a["status"] == "ok"
    assert a["n"] == n
    assert a["wins"] + a["losses"] + a["pushes"] == n
    assert a["model"] == "torvik-efficiency-mc-v1"
    assert is_valid_sim_projection(a)
    assert a["ratings_provenance"]["ratings_as_of"] == "2026-11-01"
    assert a["margin_sd"] == RULES.margin_sd
    rec = format_sim_rec(a)
    assert rec is not None and rec.startswith("proj ")
    assert str(n) in rec


def _splits(h_money, h_tick, a_money, a_tick, hline=-3.5):
    return {
        "spread": {
            "home": {"money_pct": h_money, "ticket_pct": h_tick, "line": hline, "price": -110.0},
            "away": {"money_pct": a_money, "ticket_pct": a_tick, "line": -hline, "price": -110.0},
        },
        "ml": {},
        "splits_source": "test",
    }


def test_evaluate_attaches_real_sim_not_conf_bernoulli():
    game = {
        "espn_id": "99",
        "home_team": "Duke",
        "away_team": "North Carolina",
        "neutral_site": False,
    }
    event = {
        "bookmakers": {
            "draftkings": {
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -4.5, "price": -110},
                        {"side": "away", "point": 4.5, "price": -110},
                    ]
                }
            }
        }
    }
    sp = _splits(30, 40, 70, 30, hline=-4.5)
    with_ratings = sharp3.evaluate(
        game,
        sp,
        event,
        is_mid_major_by_side={"home": False, "away": False},
        ratings=FIXTURE_RATINGS,
        ratings_provenance=FIXTURE_PROVENANCE,
        now=FIXTURE_NOW,
    )
    no_ratings = sharp3.evaluate(
        game, sp, event, is_mid_major_by_side={"home": False, "away": False}, ratings=None
    )
    assert with_ratings["sim_projection"]["status"] == "ok"
    assert with_ratings["sim_rec"] and with_ratings["sim_rec"].startswith("proj ")
    assert no_ratings["sim_rec"] is None
    assert no_ratings["sim_projection"]["status"] == "unavailable"
    # Old fabricated pattern tied conf to ~1000 Bernoulli draws (e.g. 978-22 at extreme conf).
    assert with_ratings["sim_rec"] != f"{int(round(with_ratings['conf'] * RULES.mc_sims))}-{RULES.mc_sims - int(round(with_ratings['conf'] * RULES.mc_sims))}"


def test_legacy_sim_rec_not_displayed():
    assert is_legacy_fabricated_sim_rec("978-22")
    assert not is_legacy_fabricated_sim_rec("proj 10-20/1000 MC")
    legacy = {"sim_rec": "795-205", "side": "home", "market": "spreads", "line": 37.5}
    assert "legacy synthetic" in (lab_sim_display_text(legacy) or "")
    assert "795-205" not in (lab_sim_display_text(legacy) or "")


def test_valid_sim_projection_displayed():
    game = {"espn_id": "401", "home_team": "Duke", "away_team": "North Carolina"}
    proj = _mc(game, side="home", market="spreads", line=-4.5, ratings=FIXTURE_RATINGS, n=500)
    row = {"sim_projection": proj, "sim_rec": format_sim_rec(proj)}
    text = lab_sim_display_text(row)
    assert text and text.startswith("MC projection (not graded record): proj ")
    assert is_valid_sim_projection(proj)


def test_mixed_legacy_and_valid_records():
    valid = _mc(
        {"espn_id": "1", "home_team": "Duke", "away_team": "North Carolina"},
        side="home",
        market="spreads",
        line=-3.0,
        ratings=FIXTURE_RATINGS,
        n=200,
    )
    rows = [
        {"sim_rec": "978-22"},
        {"sim_projection": valid, "sim_rec": format_sim_rec(valid)},
        {"sim_projection": {"status": "unavailable", "reason": "ratings_not_loaded"}},
    ]
    texts = [lab_sim_display_text(r) for r in rows]
    assert "legacy synthetic" in texts[0]
    assert texts[1] and "torvik-efficiency-mc-v1" in texts[1]
    assert "ratings_not_loaded" in texts[2]


def test_lab_builder_hides_legacy_sim_rec_in_html(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_ncaam_lab", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaam_lab.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = tmp_path / "data"
    (data / "ncaam").mkdir(parents=True)
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    day = now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    (data / "ncaam" / f"systems_{day.strftime('%Y%m%d')}.json").write_text(
        __import__("json").dumps(
            {
                "updated_at": now.isoformat(),
                "splits": {"n_with_money": 1, "n_games": 1},
                "games": {
                    "g1": {
                        "tip": (now + __import__("datetime").timedelta(hours=2)).isoformat(),
                        "home_team": "Louisville",
                        "away_team": "Morehead St.",
                        "has_splits": True,
                        "sharp3": {
                            "result": "play",
                            "side": "away",
                            "market": "spreads",
                            "line": 37.5,
                            "price": -110,
                            "tier": "GOLD",
                            "units": 2.0,
                            "sim_rec": "795-205",
                        },
                    }
                },
            }
        )
    )
    (data / "ncaam_ledger.json").write_text('{"plays":[]}')
    monkeypatch.setattr(mod, "DATA", data)
    page = mod.build(tmp_path / "page.html", now=now, fixture_sim_demo=True).read_text()
    assert "795-205" not in page
    assert "legacy synthetic" in page
    assert "Fixture example (not live pregame)" in page
    assert "torvik-efficiency-mc-v1" in page


def test_sim_projection_not_tied_to_splits_confidence():
    game = {"espn_id": "77", "home_team": "Duke", "away_team": "North Carolina"}
    event = {
        "bookmakers": {
            "draftkings": {
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -10.0, "price": -110},
                        {"side": "away", "point": 10.0, "price": -110},
                    ]
                }
            }
        }
    }
    sp_hi = _splits(80, 20, 20, 80, hline=-10.0)
    sp_lo = _splits(55, 45, 45, 55, hline=-10.0)
    a = sharp3.evaluate(
        game,
        sp_hi,
        event,
        is_mid_major_by_side={"home": False, "away": False},
        ratings=FIXTURE_RATINGS,
        ratings_provenance=FIXTURE_PROVENANCE,
        now=FIXTURE_NOW,
    )
    b = sharp3.evaluate(
        game,
        sp_lo,
        event,
        is_mid_major_by_side={"home": False, "away": False},
        ratings=FIXTURE_RATINGS,
        ratings_provenance=FIXTURE_PROVENANCE,
        now=FIXTURE_NOW,
    )
    assert a["conf"] != pytest.approx(b["conf"])
    assert a["sim_projection"] == b["sim_projection"]
