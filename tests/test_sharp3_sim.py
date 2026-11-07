"""Sharp 3 Monte Carlo projection (replaces fabricated sim_rec)."""

from __future__ import annotations

import importlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sharp_scout.ncaam import sharp3
from sharp_scout.ncaam import ratings as ratings_mod
from sharp_scout.ncaam.ratings import cache_date_from_path, load_ratings, ratings_provenance_for_path
from sharp_scout.ncaam.rules import RULES
from sharp_scout.ncaam.sharp3_sim import (
    DISPLAY_MAX_RATING_AGE_DAYS,
    format_sim_rec,
    is_legacy_fabricated_sim_rec,
    is_valid_sim_projection,
    lab_sim_display_text,
    monte_carlo_projection,
    run_margin_monte_carlo_core,
    validate_ratings_for_sharp3_display,
)


FIXTURE_RATINGS = load_ratings(Path("tests/fixtures/ncaam/torvik_sample.csv"))
FIXTURE_PROVENANCE = json.loads(
    (Path(__file__).parent / "fixtures" / "ncaam" / "torvik_sample.provenance.json").read_text()
)
GAME = {"espn_id": "401", "home_team": "Duke", "away_team": "North Carolina", "neutral_site": False}
EVAL_NOW = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)


def _core(**kw):
    kw.setdefault("ratings", FIXTURE_RATINGS)
    return run_margin_monte_carlo_core(GAME, side="home", market="spreads", line=-4.5, **kw)


def test_sharp3_module_has_no_random_sim_record():
    src = inspect.getsource(importlib.import_module("sharp_scout.ncaam.sharp3"))
    assert "sim_record" not in src
    assert "random.Random" not in src


def test_provenance_never_treats_cache_date_as_ratings_as_of(tmp_path):
    dated = tmp_path / "ratings_20261107.csv"
    dated.write_text("team,adjoe,adjde,adjt\nDuke,1,1,70\n", encoding="utf-8")
    assert cache_date_from_path(dated) == EVAL_NOW.date()
    prov = ratings_provenance_for_path(dated)
    assert prov["cache_date_et"] == "2026-11-07"
    assert prov["ratings_as_of"] is None
    assert prov["ratings_as_of_verified"] is False
    ok, reason = validate_ratings_for_sharp3_display(prov, now=EVAL_NOW)
    assert not ok and reason == "ratings_as_of_missing"


def test_verified_as_of_only_from_meta_not_http_last_modified(tmp_path, monkeypatch):
    csv_path = tmp_path / "ratings_20261107.csv"
    csv_path.write_bytes(b"x")
    meta = {
        "upstream_http_last_modified_utc": "2026-11-07T14:00:18+00:00",
        "csv_has_snapshot_date_field": False,
    }
    ratings_mod._meta_path_for(csv_path).write_text(json.dumps(meta))
    prov = ratings_provenance_for_path(csv_path)
    assert prov["upstream_http_last_modified_utc"] is not None
    assert prov["ratings_as_of"] is None
    assert not prov["ratings_as_of_verified"]


def test_fetch_torvik_writes_meta_with_http_last_modified(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    dest = tmp_path / "ratings_20261107.csv"

    class Resp:
        content = b"team,adjoe,adjde,adjt\nDuke,120,90,70\n"
        headers = {"last-modified": "Sat, 07 Nov 2026 14:00:18 GMT"}

        def raise_for_status(self):
            return None

    client = MagicMock()
    client.get.return_value = Resp()
    client.__enter__ = lambda s: s
    client.__exit__ = lambda *a: None
    monkeypatch.setattr(ratings_mod.httpx, "Client", lambda **kw: client)
    ratings_mod.fetch_torvik_csv(dest=dest)
    meta = json.loads(ratings_mod._meta_path_for(dest).read_text())
    assert meta["csv_has_snapshot_date_field"] is False
    assert meta["upstream_http_last_modified_utc"] is not None
    assert "ratings_source_as_of" not in meta


def test_production_monte_carlo_unavailable_without_verified_as_of():
    out = monte_carlo_projection(
        GAME,
        side="home",
        market="spreads",
        line=-4.5,
        ratings=FIXTURE_RATINGS,
        ratings_provenance=FIXTURE_PROVENANCE,
        now=EVAL_NOW,
    )
    assert out["status"] == "unavailable"
    assert out["reason"] == "ratings_as_of_missing"


def test_monte_carlo_unavailable_without_provenance():
    out = monte_carlo_projection(GAME, side="home", market="spreads", line=-4.5, ratings=None)
    assert out["reason"] == "ratings_provenance_missing"


def test_core_deterministic_reproducibility_and_counts():
    n = 2000
    a = _core(n=n)
    b = _core(n=n)
    assert a == b
    assert a["wins"] + a["losses"] + a["pushes"] == n
    assert a["reproducibility"]["seed_inputs"] == "sharp3-sim|401|home|spreads|-4.5"


def test_verified_provenance_enables_display_when_meta_has_source_as_of(tmp_path):
    csv_path = tmp_path / "ratings_20261107.csv"
    csv_path.write_text("x", encoding="utf-8")
    ratings_mod._meta_path_for(csv_path).write_text(
        json.dumps(
            {
                "ratings_source_as_of": "2026-11-07",
                "ratings_as_of_derivation": "upstream test field",
            }
        )
    )
    prov = ratings_provenance_for_path(csv_path)
    assert prov["ratings_as_of_verified"] is True
    ok, _ = validate_ratings_for_sharp3_display(prov, now=EVAL_NOW)
    assert ok
    assert DISPLAY_MAX_RATING_AGE_DAYS == 1
    stale_meta = tmp_path / "ratings_20261105.csv"
    stale_meta.write_text("x", encoding="utf-8")
    ratings_mod._meta_path_for(stale_meta).write_text(
        json.dumps({"ratings_source_as_of": "2026-11-05"})
    )
    prov_stale = ratings_provenance_for_path(stale_meta)
    ok, reason = validate_ratings_for_sharp3_display(prov_stale, now=EVAL_NOW)
    assert not ok and reason == "ratings_stale_for_display"


def _splits(h_money, h_tick, a_money, a_tick, hline=-3.5):
    return {
        "spread": {
            "home": {"money_pct": h_money, "ticket_pct": h_tick, "line": hline, "price": -110.0},
            "away": {"money_pct": a_money, "ticket_pct": a_tick, "line": -hline, "price": -110.0},
        },
        "ml": {},
        "splits_source": "test",
    }


def test_evaluate_sim_unavailable_in_production_path():
    game = {"espn_id": "99", "home_team": "Duke", "away_team": "North Carolina", "neutral_site": False}
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
    prov = dict(FIXTURE_PROVENANCE)
    ev = sharp3.evaluate(
        game,
        sp,
        event,
        is_mid_major_by_side={"home": False, "away": False},
        ratings=FIXTURE_RATINGS,
        ratings_provenance=prov,
        now=EVAL_NOW,
    )
    assert ev["sim_projection"]["status"] == "unavailable"
    assert ev["sim_rec"] is None


def test_legacy_sim_rec_not_displayed():
    assert is_legacy_fabricated_sim_rec("978-22")
    legacy = {"sim_rec": "795-205"}
    assert "legacy synthetic" in (lab_sim_display_text(legacy) or "")


def test_valid_projection_requires_verified_as_of():
    core = _core(n=500)
    assert not is_valid_sim_projection(core)
    core["ratings_provenance"] = {
        "source": "barttorvik",
        "ratings_as_of": "2026-11-07",
        "ratings_as_of_verified": True,
    }
    assert is_valid_sim_projection(core)
    text = lab_sim_display_text({"sim_projection": core, "sim_rec": format_sim_rec(core)})
    assert text and "proj " in text


def test_lab_builder_hides_legacy_sim_rec_in_html(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_ncaam_lab", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaam_lab.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = tmp_path / "data"
    (data / "ncaam").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    day = now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    (data / "ncaam" / f"systems_{day.strftime('%Y%m%d')}.json").write_text(
        json.dumps(
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
    assert "Fixture example" in page
